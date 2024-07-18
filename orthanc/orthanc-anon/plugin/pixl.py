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
Applies anonymisation scheme to datasets

This module:
-Modifies a DICOM instance received by Orthanc and applies anonymisation
-Upload the resource to a dicom-web server
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from io import BytesIO
from time import sleep
from typing import TYPE_CHECKING, cast

import requests
from core.exceptions import PixlDiscardError
from decouple import config
from loguru import logger
from pydicom import dcmread

import orthanc
from pixl_dcmd.main import (
    anonymise_and_validate_dicom,
    should_exclude_series,
    write_dataset_to_bytes,
)

if TYPE_CHECKING:
    from typing import Any

ORTHANC_USERNAME = config("ORTHANC_USERNAME")
ORTHANC_PASSWORD = config("ORTHANC_PASSWORD")
ORTHANC_URL = "http://localhost:8042"

EXPORT_API_URL = "http://export-api:8000"

# Set up logging as main entry point
logger.remove()  # Remove all handlers added so far, including the default one.
logging_level = config("LOG_LEVEL")
if not logging_level:
    logging_level = "INFO"
logger.add(sys.stdout, level=logging_level)

logger.warning("Running logging at level {}", logging_level)


def AzureAccessToken() -> str:
    """
    Send payload to oath2/token url and
    return the response
    """
    AZ_DICOM_ENDPOINT_CLIENT_ID = config("AZ_DICOM_ENDPOINT_CLIENT_ID")
    AZ_DICOM_ENDPOINT_CLIENT_SECRET = config("AZ_DICOM_ENDPOINT_CLIENT_SECRET")
    AZ_DICOM_ENDPOINT_TENANT_ID = config("AZ_DICOM_ENDPOINT_TENANT_ID")

    url = "https://login.microsoft.com/" + AZ_DICOM_ENDPOINT_TENANT_ID + "/oauth2/token"

    payload = {
        "client_id": AZ_DICOM_ENDPOINT_CLIENT_ID,
        "grant_type": "client_credentials",
        "client_secret": AZ_DICOM_ENDPOINT_CLIENT_SECRET,
        "resource": "https://dicom.healthcareapis.azure.com",
    }

    response = requests.post(url, data=payload, timeout=10)

    response_json = response.json()
    # We may wish to make use of the "expires_in" (seconds) value
    # to refresh this token less aggressively
    return cast(str, response_json["access_token"])


TIMER = None


def AzureDICOMTokenRefresh() -> None:
    """
    Refresh Azure DICOM token
    If this fails then wait 30s and try again
    If successful then access_token can be used in
    dicomweb_config to update DICOMweb token through API call
    """
    global TIMER
    TIMER = None

    orthanc.LogWarning("Refreshing Azure DICOM token")

    AZ_DICOM_TOKEN_REFRESH_SECS = int(config("AZ_DICOM_TOKEN_REFRESH_SECS"))
    AZ_DICOM_ENDPOINT_NAME = config("AZ_DICOM_ENDPOINT_NAME")
    AZ_DICOM_ENDPOINT_URL = config("AZ_DICOM_ENDPOINT_URL")
    AZ_DICOM_HTTP_TIMEOUT = int(config("HTTP_TIMEOUT"))

    try:
        access_token = AzureAccessToken()
    except Exception:  # noqa: BLE001
        orthanc.LogError(
            "Failed to get an Azure access token. Retrying in 30 seconds\n" + traceback.format_exc()
        )
        sleep(30)
        return AzureDICOMTokenRefresh()

    bearer_str = "Bearer " + access_token

    dicomweb_config = {
        "Url": AZ_DICOM_ENDPOINT_URL,
        "HttpHeaders": {
            # downstream auth token
            "Authorization": bearer_str,
        },
        "HasDelete": True,
        "Timeout": AZ_DICOM_HTTP_TIMEOUT,
    }

    headers = {"content-type": "application/json"}

    url = ORTHANC_URL + "/dicom-web/servers/" + AZ_DICOM_ENDPOINT_NAME
    # dynamically defining an DICOMWeb endpoint in Orthanc

    try:
        requests.put(
            url,
            auth=(ORTHANC_USERNAME, ORTHANC_PASSWORD),
            headers=headers,
            data=json.dumps(dicomweb_config),
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        orthanc.LogError("Failed to update DICOMweb token")
        raise SystemExit(e)  # noqa: TRY200, B904

    orthanc.LogWarning("Updated DICOMweb token")

    TIMER = threading.Timer(AZ_DICOM_TOKEN_REFRESH_SECS, AzureDICOMTokenRefresh)
    TIMER.start()
    return None


def Send(study_id: str) -> None:
    """
    Send the resource to the appropriate destination.
    Throws an exception if the image has already been exported.
    """
    msg = f"Sending {study_id}"
    logger.debug(msg)
    notify_export_api_of_readiness(study_id)


def notify_export_api_of_readiness(study_id: str):
    """
    Tell export-api that our data is ready and it should download it from us and upload
    as appropriate
    """
    url = EXPORT_API_URL + "/export-dicom-from-orthanc"
    payload = {"study_id": study_id}
    timeout: float = config("PIXL_DICOM_TRANSFER_TIMEOUT", default=180, cast=float)
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()


def should_auto_route() -> bool:
    """
    Checks whether ORTHANC_AUTOROUTE_ANON_TO_ENDPOINT environment variable is
    set to true or false
    """
    logger.trace("Checking value of autoroute")
    return os.environ.get("ORTHANC_AUTOROUTE_ANON_TO_ENDPOINT", "false").lower() == "true"


def _azure_available() -> bool:
    # Check if AZ_DICOM_ENDPOINT_CLIENT_ID is set
    return config("AZ_DICOM_ENDPOINT_CLIENT_ID", default="") != ""


def OnChange(changeType, level, resource):  # noqa: ARG001
    """
    - If a study is stable and if should_auto_route returns true
    then notify the export API that it should perform the upload of DICOM data.
    - If orthanc has started then start a timer to refresh the Azure token every 30 seconds
    - If orthanc has stopped then cancel the timer
    """
    if not should_auto_route():
        return

    if changeType == orthanc.ChangeType.STABLE_STUDY:
        msg = f"Stable study: {resource}"
        logger.info(msg)
        Send(resource)

    if changeType == orthanc.ChangeType.ORTHANC_STARTED and _azure_available():
        orthanc.LogWarning("Starting the scheduler")
        AzureDICOMTokenRefresh()
    elif changeType == orthanc.ChangeType.ORTHANC_STOPPED:
        if TIMER is not None:
            orthanc.LogWarning("Stopping the scheduler")
            TIMER.cancel()


def OnHeartBeat(output, uri, **request) -> Any:  # noqa: ARG001
    """Extends the REST API by registering a new route in the REST API"""
    orthanc.LogInfo("OK")
    output.AnswerBuffer("OK\n", "text/plain")


def ReceivedInstanceCallback(receivedDicom: bytes, origin: str) -> Any:
    """Modifies a DICOM instance received by Orthanc and applies anonymisation."""
    if origin == orthanc.InstanceOrigin.REST_API:
        orthanc.LogWarning("DICOM instance received from the REST API")
    elif origin == orthanc.InstanceOrigin.DICOM_PROTOCOL:
        orthanc.LogWarning("DICOM instance received from the DICOM protocol")

    # It's important that as much code in this handler as possible is inside this "try" block.
    # This ensures we discard the image if anything goes wrong in the anonymisation process.
    # If the handler raises an exception the pre-anon image will be kept.
    try:
        return _process_dicom_instance(receivedDicom)
    except Exception:  # noqa: BLE001
        orthanc.LogError("Failed to anonymize instance due to\n" + traceback.format_exc())
        return orthanc.ReceivedInstanceAction.DISCARD, None


def _process_dicom_instance(receivedDicom: bytes) -> tuple[orthanc.ReceivedInstanceAction, None]:
    # Read the bytes as DICOM/
    dataset = dcmread(BytesIO(receivedDicom))

    # Do before anonymisation in case someone decides to delete the
    # Series Description tag as part of anonymisation.
    if should_exclude_series(dataset):
        orthanc.LogWarning("DICOM instance discarded due to its series description")
        return orthanc.ReceivedInstanceAction.DISCARD, None

    # Attempt to anonymise and drop the study if any exceptions occur
    try:
        anonymise_and_validate_dicom(dataset)
        return orthanc.ReceivedInstanceAction.MODIFY, write_dataset_to_bytes(dataset)
    except PixlDiscardError as error:
        logger.info("Skipping instance: {}", error)
        return orthanc.ReceivedInstanceAction.DISCARD, None


orthanc.RegisterOnChangeCallback(OnChange)
orthanc.RegisterReceivedInstanceCallback(ReceivedInstanceCallback)
orthanc.RegisterRestCallback("/heart-beat", OnHeartBeat)
