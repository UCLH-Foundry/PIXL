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
import traceback
from io import BytesIO
from typing import TYPE_CHECKING

from core.dicom_tags import DICOM_TAG_PROJECT_NAME
from pydicom import Dataset, dcmread, dcmwrite

import orthanc
from pixl_dcmd.tagrecording import record_dicom_headers

if TYPE_CHECKING:
    from typing import Any


def OnChange(changeType, level, resourceId):  # noqa: ARG001
    """
    # Taken from:
    # https://book.orthanc-server.com/plugins/python.html#auto-routing-studies
    This routes any stable study to a modality named PIXL-Anon if
    should_auto_route returns true
    """
    if changeType == orthanc.ChangeType.STABLE_STUDY and should_auto_route():
        print("Stable study: %s" % resourceId)  # noqa: T201
        orthanc.RestApiPost("/modalities/PIXL-Anon/store", resourceId)


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


def write_dataset_to_bytes(dataset: Dataset) -> bytes:
    """
    Write pydicom DICOM dataset to byte array

    Original from:
    https://pydicom.github.io/pydicom/stable/auto_examples/memory_dataset.html
    """
    with BytesIO() as buffer:
        dcmwrite(buffer, dataset)
        buffer.seek(0)
        return buffer.read()


def modify_dicom_tags(receivedDicom: bytes, origin: str) -> Any:
    """
    A new incoming DICOM file needs to have the project name private tag added here, so
    that the API will later allow us to edit it.
    However, we don't know its correct value at this point, so just create it with an obvious
    placeholder value.
    """
    if origin != orthanc.InstanceOrigin.DICOM_PROTOCOL:
        # don't keep resetting the tag values if this was triggered by an API call!
        print("modify_dicom_tags - doing nothing as change triggered by API")  # noqa: T201
        return orthanc.ReceivedInstanceAction.KEEP_AS_IS, None
    dataset = dcmread(BytesIO(receivedDicom))

    # TODO: replace with `core.dicom_tags.add_private_tag`
    private_creator_name = DICOM_TAG_PROJECT_NAME.creator_string
    # See the orthanc.json config file for where this tag is given a nickname
    private_tag_offset = DICOM_TAG_PROJECT_NAME.offset_id
    # LO = Long string max 64
    # https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_6.2.html
    vr = "LO"
    unknown_value = "__pixl_unknown_value__"
    group_id = DICOM_TAG_PROJECT_NAME.group_id
    # The private block is the first free block >= 0x10.
    # We can't directly control it, but the orthanc config requires it to be
    # hardcoded to 0x10
    # https://dicom.nema.org/dicom/2013/output/chtml/part05/sect_7.8.html

    private_block = dataset.private_block(group_id, private_creator_name, create=True)
    private_block.add_new(private_tag_offset, vr, unknown_value)
    # end TODO

    print(  # noqa: T201
        f"modify_dicom_tags - added new private "
        f"block starting at 0x{private_block.block_start:x}"
    )
    if not DICOM_TAG_PROJECT_NAME.acceptable_private_block(private_block.block_start >> 8):
        print(  # noqa: T201
            "ERROR: The private block does not match the value hardcoded in the orthanc "
            "config. This can be because there was an unexpected pre-existing private block"
            f"in group {group_id}"
        )
    return orthanc.ReceivedInstanceAction.MODIFY, write_dataset_to_bytes(dataset)


def SendResourceToAnon(output, uri, **request):  # noqa: ARG001
    """Send an existing study to the anon modality"""
    orthanc.LogWarning(f"Received request to send study to anon modality: {request}")
    if not should_auto_route():
        orthanc.LogWarning("Auto-routing is not enabled, dropping request {request}")
        output.answerBuffer("Auto-routing is not enabled", "text/plain")
        return
    try:
        body = json.loads(request["body"])
        resource_id = body["ResourceId"]
        orthanc.RestApiPost("/modalities/PIXL-Anon/store", resource_id)
        output.AnswerBuffer("OK", "text/plain")
        orthanc.LogInfo(f"Succesfully sent study to anon modality: {resource_id}")
    except:  # noqa: E722
        orthanc.LogWarning(f"Failed to send study to anon:\n{traceback.format_exc()}")
        output.AnswerBuffer("Failed to send study to anon", "text/plain")


orthanc.RegisterOnChangeCallback(OnChange)
orthanc.RegisterReceivedInstanceCallback(ReceivedInstanceCallback)
orthanc.RegisterRestCallback("/heart-beat", OnHeartBeat)
orthanc.RegisterRestCallback("/send-to-anon", SendResourceToAnon)
