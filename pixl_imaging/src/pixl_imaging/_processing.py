#  Copyright (c) University College London Hospitals NHS Foundation Trust
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
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.dicom_tags import DICOM_TAG_PROJECT_NAME
from decouple import config

from pixl_imaging._orthanc import Orthanc, PIXLRawOrthanc

if TYPE_CHECKING:
    from core.patient_queue.message import Message

logger = logging.getLogger("uvicorn")


async def process_message(message: Message) -> None:
    """
    Process message from queue by retrieving a study with the given Patient and Accession Number.
    We may receive multiple messages with same Patient + Acc Num, either as retries or because
    they are needed for multiple projects.
    """
    logger.debug("Processing: %s", message)

    study = ImagingStudy.from_message(message)
    orthanc_raw = PIXLRawOrthanc()

    study_exists = _update_or_resend_existing_study_(message.project_name, orthanc_raw, study)
    if study_exists:
        return

    # Tell orthanc to query VNA for the patient and accession number
    query_id = orthanc_raw.query_remote(study.orthanc_query_dict, modality=config("VNAQR_MODALITY"))
    if query_id is None:
        logger.error("Failed to find %s in the VNA", study)
        raise RuntimeError

    # Wait for query to complete
    timeout = config("PIXL_DICOM_TRANSFER_TIMEOUT", cast=float)
    try:
        await orthanc_raw.wait_for_job_success(query_id, timeout)
    except TimeoutError as te:
        msg = f"Failed to transfer {message} within {timeout} seconds"
        raise TimeoutError(msg) from te

    # Now that instance has arrived in orthanc raw, we can set its project name tag via the API
    studies_with_tags = orthanc_raw.query_local(study.orthanc_query_dict)
    logger.debug("Local instances with matching tags: %s", studies_with_tags)

    _add_project_to_study(message.project_name, orthanc_raw, studies_with_tags)

    return


def _update_or_resend_existing_study_(
    project_name: str, orthanc_raw: PIXLRawOrthanc, study: ImagingStudy
) -> bool:
    """
    If study does not yet exist in orthanc raw, do nothing.
    If study exists in orthanc raw and has the wrong project name, update it.
    If study exists in orthanc raw and has the correct project name, send to orthanc anon.

    Return True if study exists in orthanc raw, otherwise False.
    """
    existing_resources = study.query_local(orthanc_raw, project_tag=True)
    if len(existing_resources) == 0:
        return False

    # Check whether study already has the correct project name
    different_project: list[str] = []
    for resource in existing_resources:
        project_tags = (
            resource["RequestedTags"].get(DICOM_TAG_PROJECT_NAME.tag_nickname),
            resource["RequestedTags"].get(
                "Unknown Tag & Data"
            ),  # Fallback for testing where we're not using the entire plugin, remains undefined
        )
        if project_name not in project_tags:
            different_project.append(resource["ID"])

    if different_project:
        _add_project_to_study(project_name, orthanc_raw, different_project)
        return True
    orthanc_raw.send_existing_study_to_anon(existing_resources[0]["ID"])
    return True


def _add_project_to_study(
    project_name: str, orthanc_raw: PIXLRawOrthanc, studies_with_tags: list[str]
) -> None:
    if len(studies_with_tags) != 1:
        logger.error(
            "Got %s studies with matching accession number and patient ID, expected 1",
            len(studies_with_tags),
        )
    for study in studies_with_tags:
        logger.debug("Study ID %s", study)
        orthanc_raw.modify_private_tags_by_study(
            study_id=study,
            private_creator=DICOM_TAG_PROJECT_NAME.creator_string,
            tag_replacement={
                # The tag here needs to be defined in orthanc's dictionary
                DICOM_TAG_PROJECT_NAME.tag_nickname: project_name,
            },
        )


@dataclass
class ImagingStudy:
    """Dataclass for DICOM study unique to a patient and imaging study"""

    message: Message

    @classmethod
    def from_message(cls, message: Message) -> ImagingStudy:
        """Build an imaging study from a queue message."""
        return ImagingStudy(message=message)

    @property
    def orthanc_query_dict(self) -> dict:
        """Build a dictionary to query a study."""
        return {
            "Level": "Study",
            "Query": {
                "PatientID": self.message.mrn,
                "AccessionNumber": self.message.accession_number,
            },
        }

    @property
    def orthanc_dict_with_project_name(self) -> dict:
        """Dictionary to query a study, returning the PIXL_PROJECT tags for each study."""
        return {
            **self.orthanc_query_dict,
            "RequestedTags": [DICOM_TAG_PROJECT_NAME.tag_nickname],
            "Expand": True,
        }

    def query_local(self, node: Orthanc, *, project_tag: bool = False) -> Any:
        """Does this study exist in an Orthanc instance/node, optionally query for project tag."""
        query_dict = self.orthanc_query_dict
        if project_tag:
            query_dict = self.orthanc_dict_with_project_name

        return node.query_local(query_dict)
