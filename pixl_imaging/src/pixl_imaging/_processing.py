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
    """
    Retrieve a study from the archives and send it to Orthanc Anon.

    If the study already exists in Orthanc Raw:
        - query VNA / PASC to determine whether any instances are missing
        - retrieve any missing instances

    If it doesn't already exist in Orthanc Raw:
        - query the VNA / PACS for the study
        - retrieve the study from the VNA / PACS

    Then:
        - set the project name tag for the study if it's not already set
        - send the study to Orthanc Anon
    """
    await orthanc_raw.raise_if_pending_jobs()
    logger.info("Processing: {}", study.message.identifier)

    timeout: int = config("PIXL_DICOM_TRANSFER_TIMEOUT", cast=int)
    existing_resource = await _get_existing_study(
        orthanc_raw=orthanc_raw,
        study=study,
    )

    if not existing_resource:
        await _retrieve_study(
            orthanc_raw=orthanc_raw,
            study=study,
            timeout=timeout,
        )
    else:
        await _retrieve_missing_instances(
            resource=existing_resource,
            orthanc_raw=orthanc_raw,
            study=study,
            timeout=timeout,
        )

    # Now that study has arrived in orthanc raw, we can set its project name tag via the API
    resource = await _get_existing_study(
        orthanc_raw=orthanc_raw,
        study=study,
    )
    if not await _project_name_is_correct(
        project_name=study.message.project_name,
        resource=resource,
    ):
        await _add_project_to_study(
            project_name=study.message.project_name,
            orthanc_raw=orthanc_raw,
            study=resource["ID"],
            timeout=timeout,
        )

    logger.debug("Local instances for study: {}", resource)
    await orthanc_raw.send_study_to_anon(resource_id=resource["ID"])


async def _get_existing_study(
    orthanc_raw: PIXLRawOrthanc,
    study: ImagingStudy,
) -> dict:
    """
    If study does not yet exist in orthanc raw, return empty dict.
    Otherwise if multiple studies exist, keep the most recently updated one.
    """
    existing_resources = await study.query_local(orthanc_raw, project_tag=True)
    if len(existing_resources) == 0:
        return {}

    # keep the most recently updated study only
    return await _delete_old_studies(
        resources=existing_resources,
        orthanc_raw=orthanc_raw,
    )


async def _delete_old_studies(
    resources: list[dict],
    orthanc_raw: PIXLRawOrthanc,
) -> dict:
    """Delete old studies from Orthanc Raw."""
    sorted_resources = sorted(
        resources,
        key=lambda resource: datetime.datetime.fromisoformat(resource["LastUpdate"]),
    )
    most_recent_resource = sorted_resources.pop(-1)
    if sorted_resources:
        logger.debug(
            "Found {} resources for study, only keeping the last updated resource: {}",
            len(sorted_resources) + 1,
            most_recent_resource,
        )
    for delete_resource in sorted_resources:
        await orthanc_raw.delete(f"/studies/{delete_resource['ID']}")

    return most_recent_resource


async def _project_name_is_correct(
    project_name: str,
    resource: dict,
) -> bool:
    """
    Check if the project name is different from the project tags.

    Returns True if the project name is in the project tags, False otherwise.
    """
    project_tags = (
        resource["RequestedTags"].get(DICOM_TAG_PROJECT_NAME.tag_nickname),
        resource["RequestedTags"].get(
            "Unknown Tag & Data"
        ),  # Fallback for testing where we're not using the entire plugin, remains undefined
    )
    return project_name in project_tags


async def _add_project_to_study(
    project_name: str,
    orthanc_raw: PIXLRawOrthanc,
    study: str,
    timeout: int,
) -> None:
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


async def _find_study_in_archives_or_raise(
    orthanc_raw: Orthanc, study: ImagingStudy
) -> tuple[str, str]:
    """
    Query primary and secondary archives for a study.

    The following steps are taken until either a query ID is returned or a PixlDiscardError is
    raised:

    1. Query the primary archive for the study using its UID. If UID is not available, query on
      MRN and accession number
        i) Return the primary archive aet modality and query id if the study is found.
        ii) If not found in the primary archive, and the secondary archive is the same as the
            primary,
      raise a PixlDiscardError.
        iii) If not found in the primary archive and it is daytime or the weekend, raise a
            PixlDiscardError.
    2. Query the secondary archive using the study UID. If UID is not available, query on
      MRN + accession number.
        a) If not found, raise a PixlDiscardError.
        a) If found in the secondary archive, return the modality and query id.
    """
    primary_modality = config("PRIMARY_DICOM_SOURCE_MODALITY")
    query_id = await _find_study_in_archive(
        orthanc_raw=orthanc_raw,
        study=study,
        modality=primary_modality,
    )

    if query_id is not None:
        return primary_modality, query_id

    if config("SECONDARY_DICOM_SOURCE_AE_TITLE") == config("PRIMARY_DICOM_SOURCE_AE_TITLE"):
        msg = (
            f"Failed to find study {study.message.identifier} in primary archive "
            "and SECONDARY_DICOM_SOURCE_AE_TITLE is the same as PRIMARY_DICOM_SOURCE_AE_TITLE."
        )
        raise PixlDiscardError(msg)

    if _is_daytime() or _is_weekend():
        msg = (
            f"Failed to find study {study.message.identifier} in primary archive. "
            "Not querying secondary archive during the daytime or on the weekend."
        )
        raise PixlDiscardError(msg)

    logger.debug(
        "Failed to find study {} in primary archive, trying secondary archive",
        study.message.identifier,
    )
    secondary_modality = config("SECONDARY_DICOM_SOURCE_MODALITY")
    query_id = await _find_study_in_archive(
        study=study,
        orthanc_raw=orthanc_raw,
        modality=secondary_modality,
    )

    if query_id is None:
        msg = f"Failed to find study {study.message.identifier} in primary or secondary archive."
        raise PixlDiscardError(msg)

    return secondary_modality, query_id


async def _find_study_in_archive(
    orthanc_raw: Orthanc,
    study: ImagingStudy,
    modality: str,
) -> Optional[str]:
    """
    Query the primary archive for the study using its UID.
    If UID is not available, query on MRN and accession number.
    """
    query_response = None
    if study.message.study_uid:
        query_response = await orthanc_raw.query_remote(
            data=study.orthanc_uid_query_dict,
            modality=modality,
        )
    if query_response is not None:
        return query_response

    logger.debug(
        "No study found in modality {} with UID '{}', trying MRN and accession number",
        modality,
        study.message.study_uid,
    )
    return await orthanc_raw.query_remote(
        study.orthanc_query_dict,
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


async def _retrieve_study(orthanc_raw: Orthanc, study: ImagingStudy, timeout: int) -> None:
    """Retrieve all instances for a study from the VNA / PACS."""
    _, query_id = await _find_study_in_archives_or_raise(orthanc_raw, study)
    job_id = await orthanc_raw.retrieve_from_remote(query_id=query_id)  # C-Move
    await orthanc_raw.wait_for_job_success_or_raise(job_id, "c-move", timeout)


async def _retrieve_missing_instances(
    resource: dict, orthanc_raw: Orthanc, study: ImagingStudy, timeout: int
) -> None:
    """Retrieve missing instances for a study from the VNA / PACS."""
    modality, missing_instance_uids = await _get_missing_instances(
        orthanc_raw, study, resource, timeout
    )
    if not missing_instance_uids:
        return
    logger.debug(
        "Retrieving {} missing instances for study {}",
        len(missing_instance_uids),
        study.message.identifier,
    )
    job_id = await orthanc_raw.retrieve_instances_from_remote(
        modality, missing_instance_uids, timeout + 60
    )  # Temporarily increasing timeout for job
    await orthanc_raw.wait_for_job_success_or_raise(job_id, "c-move for missing instances", timeout)


async def _get_missing_instances(
    orthanc_raw: Orthanc,
    study: ImagingStudy,
    resource: dict,
    timeout: int,
) -> tuple[str, list[dict[str, str]]]:
    """
    Check if any study instances are missing from Orthanc Raw.

    Return a tuple of the modality and a list missing instance UIDs (empty if none missing)
    """
    # First get all SOPInstanceUIDs for the study that are in Orthanc Raw
    orthanc_raw_sop_instance_uids = []
    for series_id in resource["Series"]:
        series = await orthanc_raw.query_local_series(series_id)
        for instance_id in series["Instances"]:
            instance = await orthanc_raw.query_local_instance(instance_id)
            orthanc_raw_sop_instance_uids.append(instance["MainDicomTags"]["SOPInstanceUID"])

    # Now query the VNA / PACS for the study instances
    modality, study_query_id = await _find_study_in_archives_or_raise(orthanc_raw, study)
    study_query_answers = await orthanc_raw.get_remote_query_answers(study_query_id)
    instances_query_id = await orthanc_raw.get_remote_query_answer_instances(
        query_id=study_query_id, answer_id=study_query_answers[0], timeout=timeout
    )
    instances_query_answers = await orthanc_raw.get_remote_query_answers(instances_query_id)

    missing_instances: list[dict[str, str]] = []

    if len(instances_query_answers) == len(orthanc_raw_sop_instance_uids):
        return modality, missing_instances

    # If the SOPInstanceUID is not in the list of instances in Orthanc Raw
    # retrieve the instance from the VNA / PACS
    query_tags = ["0020,000d", "0020,000e", "0008,0018"]
    for instance_query_answer in instances_query_answers:
        instance_query_answer_content = await orthanc_raw.get_remote_query_answer_content(
            query_id=instances_query_id,
            answer_id=instance_query_answer,
        )
        uids_for_query = {
            instance_query_answer_content[x]["Name"]: instance_query_answer_content[x]["Value"]
            for x in query_tags
        }
        sop_instance_uid = uids_for_query["SOPInstanceUID"]
        if sop_instance_uid in orthanc_raw_sop_instance_uids:
            continue

        logger.trace(
            "Instance {} is missing from study {}",
            sop_instance_uid,
            study.message.study_uid,
        )
        missing_instances.append(uids_for_query)

    return modality, missing_instances


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
            },
        }

    @property
    def query_project_name(self) -> dict:
        """Dictionary to query a study, returning the PIXL_PROJECT tags for each study."""
        return {
            "RequestedTags": [DICOM_TAG_PROJECT_NAME.tag_nickname],
            "Expand": True,
        }

    async def query_local(self, node: Orthanc, *, project_tag: bool = False) -> Any:
        """Does this study exist in an Orthanc instance/node, optionally query for project tag."""
        uid_query = self.orthanc_uid_query_dict
        if project_tag:
            uid_query = uid_query | self.query_project_name

        query_response = await node.query_local(uid_query)
        if query_response:
            return query_response

        logger.trace(
            "No study found locally with UID, trying MRN and accession number. {}",
            self.orthanc_query_dict,
        )

        mrn_accession_query = self.orthanc_query_dict
        if project_tag:
            mrn_accession_query = mrn_accession_query | self.query_project_name

        return await node.query_local(mrn_accession_query)
