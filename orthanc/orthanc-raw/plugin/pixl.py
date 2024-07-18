#  Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
Facilitates routing of stable studies from orthanc-raw to orthanc-anon

This module provides:
-OnChange: route stable studies and if auto-routing enabled
-should_auto_route: checks whether auto-routing is enabled
-OnHeartBeat: extends the REST API
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from io import BytesIO
from typing import TYPE_CHECKING, Optional

from core.dicom_tags import DICOM_TAG_PROJECT_NAME, add_private_tag
from core.exceptions import PixlRequeueMessageError
from decouple import config
from loguru import logger
from pydicom import dcmread

import orthanc
from pixl_dcmd.main import write_dataset_to_bytes
from pixl_dcmd.tagrecording import record_dicom_headers

if TYPE_CHECKING:
    from typing import Any

# Set up logging as main entry point
logger.remove()  # Remove all handlers added so far, including the default one.
logging_level = config("LOG_LEVEL")
if not logging_level:
    logging_level = "INFO"
logger.add(sys.stdout, level=logging_level)

logger.warning("Running logging at level {}", logging_level)


def OnChange(changeType, level, resourceId):  # noqa: ARG001
    """
    # Taken from:
    # https://book.orthanc-server.com/plugins/python.html#auto-routing-studies
    This routes any stable study to a modality named PIXL-Anon if
    should_auto_route returns true
    """
    if changeType != orthanc.ChangeType.STABLE_STUDY:
        return

    # imaging-api didn't get to updating pixl project name, could be incomplete so delete
    if _get_project_name_from_study_id(resourceId) == DICOM_TAG_PROJECT_NAME.PLACEHOLDER_VALUE:
        logger.warning("Study {} has not been set with a pixl project name, deleting", resourceId)
        orthanc.RestApiDelete(f"/studies/{resourceId}")
        return

    if should_auto_route():
        logger.debug("Sending study: {}", resourceId)
        # Although this can throw, since we have nowhere to report errors
        # back to (e.g. an HTTP client), don't try to handle anything here.
        # The client will have to detect that it hasn't happened and retry.
        orthanc_anon_store_study(resourceId)


def _get_project_name_from_study_id(study_id: str) -> str:
    response_study = orthanc.RestApiGet(f"/studies/{study_id}/shared-tags?simplify=true")
    json_response = json.loads(response_study)
    return json_response["UCLHPIXLProjectName"]


def orthanc_anon_store_study(resource_id):
    """Call the API to send the specified resource (study) to the orthanc anon server."""
    # RestApiPost raises an orthanc.OrthancException if it fails
    try:
        orthanc.RestApiPost("/modalities/PIXL-Anon/store", resource_id)
    except orthanc.OrthancException as exception:
        # If there's invalid dicom we should delete the resource and retry pulling the data again
        if exception.message == "Bad file format":
            orthanc.RestApiDelete(f"/studies/{resource_id}")
        raise PixlRequeueMessageError from exception
    orthanc.LogInfo(f"Successfully sent study to anon modality: {resource_id}")


def OnHeartBeat(output, uri, **request):  # noqa: ARG001
    """Extends the REST API by registering a new route in the REST API"""
    orthanc.LogWarning("OK")
    output.AnswerBuffer("OK\n", "text/plain")


def ReceivedInstanceCallback(receivedDicom: bytes, origin: str) -> Any:
    """Optionally record headers from the received DICOM instance."""
    if should_record_headers():
        record_dicom_headers(receivedDicom)
    return modify_dicom_tags(receivedDicom, origin)


def should_record_headers() -> bool:
    """
    Checks whether ORTHANC_RAW_RECORD_HEADERS environment variable is
    set to true or false
    """
    return os.environ.get("ORTHANC_RAW_RECORD_HEADERS", "false").lower() == "true"


def should_auto_route():
    """
    Checks whether ORTHANC_AUTOROUTE_RAW_TO_ANON environment variable is
    set to true or false
    """
    return os.environ.get("ORTHANC_AUTOROUTE_RAW_TO_ANON", "false").lower() == "true"


def modify_dicom_tags(receivedDicom: bytes, origin: str) -> Any:
    """
    A new incoming DICOM file needs to have the project name private tag added here, so
    that the API will later allow us to edit it.
    However, we don't know its correct value at this point, so just create it with an obvious
    placeholder value.
    """
    if origin != orthanc.InstanceOrigin.DICOM_PROTOCOL:
        # don't keep resetting the tag values if this was triggered by an API call!
        logger.trace("doing nothing as change triggered by API")
        return orthanc.ReceivedInstanceAction.KEEP_AS_IS, None
    dataset = dcmread(BytesIO(receivedDicom))
    # See the orthanc.json config file for where this tag is given a nickname
    # The private block is the first free block >= 0x10.
    # We can't directly control it, but the orthanc config requires it to be
    # hardcoded to 0x10
    # https://dicom.nema.org/dicom/2013/output/chtml/part05/sect_7.8.html

    # Add project name as private tag, at this point, the value is unknown
    private_block = add_private_tag(dataset, DICOM_TAG_PROJECT_NAME)

    logger.debug("added new private block starting at 0x{:04x}", private_block.block_start)
    return orthanc.ReceivedInstanceAction.MODIFY, write_dataset_to_bytes(dataset)


def log_and_return_http(
    output, http_code: int, http_message: str, log_message: Optional[str] = None
):
    """
    Log and make an HTTP response in case of success or failure. For failure, log
    a stack/exception trace as well.

    :param output: the orthanc output object as given to the callback function
    :param http_code: HTTP code to return
    :param http_message: message to return in HTTP body
    :param log_message: message to log, if different to http_message.
                        If None, do not log at all if success
    """
    http_json_str = json.dumps({"Message": http_message})
    if http_code == 200:  # noqa: PLR2004
        if log_message:
            orthanc.LogInfo(log_message)
        output.AnswerBuffer(http_json_str, "application/json")
    else:
        orthanc.LogWarning(f"{log_message or http_message}:\n{traceback.format_exc()}")
        # length needed in bytes not chars
        output.SendHttpStatus(http_code, http_json_str, len(http_json_str.encode()))


def SendResourceToAnon(output, uri, **request):  # noqa: ARG001
    """Send an existing study to the anon modality"""
    orthanc.LogWarning(f"Received request to send study to anon modality: {request}")
    if not should_auto_route():
        log_and_return_http(
            output,
            200,
            "Auto-routing is not enabled",
            f"Auto-routing is not enabled, dropping request {request}",
        )
        return
    try:
        body = json.loads(request["body"])
        resource_id = body["ResourceId"]
    except (json.decoder.JSONDecodeError, KeyError):
        err_str = "Body needs to be JSON with key ResourceId"
        log_and_return_http(output, 400, err_str)
    except:
        err_str = "Other error decoding request"
        log_and_return_http(output, 500, err_str)
        raise

    try:
        orthanc_anon_store_study(resource_id)
    except orthanc.OrthancException:
        err_str = "Failed contacting downstream server"
        log_and_return_http(output, 502, err_str)
    except PixlRequeueMessageError:
        err_str = "Invalid DICOM, should requeue message"
        log_and_return_http(output, 422, err_str)
    except:
        err_str = "Misc error sending study to anon"
        log_and_return_http(output, 500, err_str)
        raise
    else:
        log_and_return_http(output, 200, "OK")


orthanc.RegisterOnChangeCallback(OnChange)
orthanc.RegisterReceivedInstanceCallback(ReceivedInstanceCallback)
orthanc.RegisterRestCallback("/heart-beat", OnHeartBeat)
orthanc.RegisterRestCallback("/send-to-anon", SendResourceToAnon)
