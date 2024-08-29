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

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

from core.dicom_tags import DICOM_TAG_PROJECT_NAME
from core.exceptions import PixlDiscardError
from decouple import config

from pixl_imaging._orthanc import Orthanc, PIXLRawOrthanc

if TYPE_CHECKING:
    from core.patient_queue.message import Message

from loguru import logger


async def process_message(message: Message) -> None:
    """
    Process message from queue by retrieving a study with the given Patient and Accession Number.
    We may receive multiple messages with same Patient + Acc Num, either as retries or because
    they are needed for multiple projects.
    """
    logger.trace("Processing: {}", message.identifier)

    study = ImagingStudy.from_message(message)
    orthanc_raw = PIXLRawOrthanc()
    await _process_message(study, orthanc_raw)


async def _process_message(study: ImagingStudy, orthanc_raw: PIXLRawOrthanc) -> None:
    await orthanc_raw.raise_if_pending_jobs()
    logger.info("Processing: {}", study.message.identifier)

    timeout: float = config("PIXL_DICOM_TRANSFER_TIMEOUT", cast=float)
    study_exists = await _update_or_resend_existing_study_(
        study.message.project_name, orthanc_raw, study, timeout
    )
    if study_exists:
        return

    query_id = await _find_study_in_archives_or_raise(orthanc_raw, study)
    job_id = await orthanc_raw.retrieve_from_remote(query_id=query_id)  # C-Move
    await orthanc_raw.wait_for_job_success_or_raise(job_id, "c-move", timeout)

    # Now that instance has arrived in orthanc raw, we can set its project name tag via the API
    studies = await orthanc_raw.query_local(study.orthanc_query_dict)
    logger.debug("Local instances for study: {}", studies)
    await _add_project_to_study(
        study.message.project_name,
        orthanc_raw,
        studies,
        timeout=timeout,
        image_identifier=study.message.identifier,
    )

    return


async def _update_or_resend_existing_study_(
    project_name: str, orthanc_raw: PIXLRawOrthanc, study: ImagingStudy, timeout: float
) -> bool:
    """
    If study does not yet exist in orthanc raw, do nothing.
    If study exists in orthanc raw and has the wrong project name, update it.
    If study exists in orthanc raw and has the correct project name, send to orthanc anon.

    Return True if study exists in orthanc raw, otherwise False.
    """
    existing_resources = await study.query_local(orthanc_raw, project_tag=True)
    if len(existing_resources) == 0:
        return False

    # Check whether study already has the correct project name
    different_project: list[str] = []

    if len(existing_resources) > 1:
        # Only keep one study, the one which has the largest number of series
        sorted_resources = sorted(existing_resources, key=lambda x: len(x["LastUpdate"]))
        logger.debug(
            "Found more than one resource for study, only keeping the last updated resource: {}",
            sorted_resources,
        )
        existing_resources = [sorted_resources.pop(-1)]
        for delete_resource in sorted_resources:
            await orthanc_raw.delete(f"/studies/{delete_resource['ID']}")

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
        await _add_project_to_study(
            project_name,
            orthanc_raw,
            different_project,
            timeout=timeout,
            image_identifier=study.message.identifier,
        )
        return True
    await orthanc_raw.send_existing_study_to_anon(existing_resources[0]["ID"])
    return True


async def _add_project_to_study(
    project_name: str,
    orthanc_raw: PIXLRawOrthanc,
    studies: list[str],
    timeout: float,
    image_identifier: str,
) -> None:
    if len(studies) > 1:
        logger.warning("Got {} studies matching {}, expected 1", studies, image_identifier)
    for study in studies:
        logger.debug("Adding private tag to study ID {}", study)
        await orthanc_raw.modify_private_tags_by_study(
            study_id=study,
            private_creator=DICOM_TAG_PROJECT_NAME.creator_string,
            tag_replacement={
                # The tag here needs to be defined in orthanc's dictionary
                DICOM_TAG_PROJECT_NAME.tag_nickname: project_name,
            },
            timeout=timeout,
        )


async def _find_study_in_archives_or_raise(orthanc_raw: Orthanc, study: ImagingStudy) -> str:
    """
    Query primary and secondary archives for a study.

    The following steps are taken until either a query ID is returned or a PixlDiscardError is
    raised:

    1. Query the primary archive for the study using its UID. If UID is not available, query on
      MRN and accession number
        i) Return the query id if the study is found.
        ii) If not found in the primary archive, and the secondary archive is the same as the
            primary,
      raise a PixlDiscardError.
        iii) If not found in the primary archive and it is daytime or the weekend, raise a
            PixlDiscardError.
    2. Query the secondary archive using the study UID. If UID is not available, query on
      MRN + accession number.
        a) If not found, raise a PixlDiscardError.
        a) If found in the ONLINE secondary archive, return the query id.
        b) if found in the secondary archive but not ONLINE, raise a PixlDiscardError.
    """
    query_id = await _find_study_in_archive(
        orthanc_raw=orthanc_raw,
        study=study,
        modality=config("PRIMARY_DICOM_SOURCE_MODALITY"),
    )

    if query_id is not None:
        return str(query_id)

    if config("SECONDARY_DICOM_SOURCE_AE_TITLE") == config("PRIMARY_DICOM_SOURCE_AE_TITLE"):
        msg = (
            f"Failed to find study {study.message.study_uid} in primary archive "
            "and SECONDARY_DICOM_SOURCE_AE_TITLE is the same as PRIMARY_DICOM_SOURCE_AE_TITLE."
        )
        raise PixlDiscardError(msg)

    if _is_daytime() or _is_weekend():
        msg = (
            f"Failed to find study {study.message.study_uid} in primary archive. "
            "Not querying secondary archive during the daytime or on the weekend."
        )
        raise PixlDiscardError(msg)

    logger.info(
        "Failed to find study {} in primary archive, trying secondary archive",
        study.message.study_uid,
    )
    query_id = await _find_study_in_archive(
        study=study,
        orthanc_raw=orthanc_raw,
        modality=config("SECONDARY_DICOM_SOURCE_MODALITY"),
    )

    if query_id is None:
        msg = f"Failed to find study {study.message.study_uid} in primary or secondary archive."
        raise PixlDiscardError(msg)

    # Check the study is in the online secondary archive
    query_answers = await orthanc_raw.get_remote_query_answers(query_id)
    query_answer_content = await orthanc_raw.get_remote_query_answer_content(
        query_id=query_id,
        answer_id=query_answers[0],
    )
    availability_tag = "0008,0056"
    availability = query_answer_content[availability_tag]["Value"]
    if availability != "ONLINE":
        msg = (
            f"Study {study.message.study_uid} found in {availability} secondary archive "
            "but we only pull from the online secondary archive."
        )
        raise PixlDiscardError(msg)

    return query_id


async def _find_study_in_archive(
    orthanc_raw: Orthanc,
    study: ImagingStudy,
    modality: str,
) -> Optional[str]:
    """
    Query the primary archive for the study using its UID.
    If UID is not available, query on MRN and accession number.
    """
    # We don't want to normalize the query otherwise only MainDicomTags will be returned
    # (InstanceAvailability will be ignored)
    additional_data = {"Normalize": False}
    query_response = None
    if study.message.study_uid:
        query_response = await orthanc_raw.query_remote(
            data=study.orthanc_uid_query_dict | additional_data,
            modality=modality,
        )

    if query_response is not None:
        return query_response

    logger.info(
        "No study found in modality {} with UID '{}', trying MRN and accession number",
        modality,
        study.message.study_uid,
    )
    return await orthanc_raw.query_remote(
        study.orthanc_query_dict | additional_data,
        modality=modality,
    )


def _is_daytime() -> bool:
    """Check if the current time is between 8 am and 8 pm."""
    timezone = ZoneInfo(config("TZ"))
    after_8am = datetime.time(8, 00) <= datetime.datetime.now(tz=timezone).time()
    before_8pm = datetime.datetime.now(tz=timezone).time() <= datetime.time(20, 00)
    return after_8am and before_8pm


def _is_weekend() -> bool:
    """Check if it's the weekend."""
    timezone = ZoneInfo(config("TZ"))
    saturday = 5
    sunday = 6
    return datetime.datetime.now(tz=timezone).weekday() in (saturday, sunday)


@dataclass
class ImagingStudy:
    """Dataclass for DICOM study unique to a patient and imaging study"""

    message: Message

    @classmethod
    def from_message(cls, message: Message) -> ImagingStudy:
        """Build an imaging study from a queue message."""
        return ImagingStudy(message=message)

    @property
    def orthanc_uid_query_dict(self) -> dict:
        """Build a dictionary to query a study with a study UID."""
        return {
            "Level": "Study",
            "Query": {
                "StudyInstanceUID": self.message.study_uid,
                "InstanceAvailability": "",
            },
        }

    @property
    def orthanc_query_dict(self) -> dict:
        """Build a dictionary to query a study on MRN and accession number."""
        return {
            "Level": "Study",
            "Query": {
                "PatientID": self.message.mrn,
                "AccessionNumber": self.message.accession_number,
                "InstanceAvailability": "",
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

    async def query_local(self, node: Orthanc, *, project_tag: bool = False) -> Any:
        """Does this study exist in an Orthanc instance/node, optionally query for project tag."""
        query_dict = self.orthanc_query_dict
        if project_tag:
            query_dict = self.orthanc_dict_with_project_name

        return await node.query_local(query_dict)
