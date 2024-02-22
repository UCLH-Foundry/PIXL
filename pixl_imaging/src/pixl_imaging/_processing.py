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
import os
from asyncio import sleep
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

from decouple import config

from pixl_imaging._orthanc import Orthanc, PIXLRawOrthanc

if TYPE_CHECKING:
    from core.patient_queue.message import Message

logger = logging.getLogger("uvicorn")
logger.setLevel(os.environ.get("LOG_LEVEL", "WARNING"))


async def process_message(message: Message) -> None:
    logger.info("Processing: %s", message)

    study = ImagingStudy.from_message(message)
    orthanc_raw = PIXLRawOrthanc()

    if study.exists_in(orthanc_raw):
        logger.info("Study exists in cache")
        return

    query_id = orthanc_raw.query_remote(study.orthanc_query_dict, modality=config("VNAQR_MODALITY"))
    if query_id is None:
        logger.error("Failed to find %s in the VNA", study)
        raise RuntimeError

    logger.debug("Found study %s in cache", study)

    job_id = orthanc_raw.retrieve_from_remote(query_id=query_id)  # C-Move
    job_state = "Pending"
    start_time = time()

    while job_state != "Success":
        if (time() - start_time) > config("PIXL_DICOM_TRANSFER_TIMEOUT", cast=float):
            msg = (
                f"Failed to transfer {message} within "
                f"{config('PIXL_DICOM_TRANSFER_TIMEOUT')} seconds"
            )
            raise TimeoutError(msg)

        await sleep(0.1)
        job_state = orthanc_raw.job_state(job_id=job_id)
    logger.info("Finished processing: %s", message)

    return


@dataclass
class ImagingStudy:
    """Dataclass for DICOM study unique to a patient and imaging study"""

    message: Message

    @classmethod
    def from_message(cls, message: Message) -> ImagingStudy:
        return ImagingStudy(message=message)

    @property
    def orthanc_query_dict(self) -> dict:
        return {
            "Level": "Study",
            "Query": {
                "PatientID": self.message.mrn,
                "AccessionNumber": self.message.accession_number,
            },
        }

    def exists_in(self, node: Orthanc) -> bool:
        """Does this study exist in an Orthanc instance/node?"""
        return len(node.query_local(self.orthanc_query_dict)) > 0
