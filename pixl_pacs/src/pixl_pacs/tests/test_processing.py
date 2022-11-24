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
"""
These tests require executing from within the PACS API container with the dependent
services being up
"""
import os

from pixl_pacs._orthanc import Orthanc, PIXLRawOrthanc
from pixl_pacs._processing import process_message, ImagingStudy
from pixl_pacs.utils import env_var
from pydicom import dcmread
from pydicom.data import get_testdata_file

STUDY_ID = "abc"
PATIENT_ID = "a_patient"

# TODO: replace with serialisation function
message_body = f"{PATIENT_ID},{STUDY_ID},01/01/1234 01:23:45".encode("utf-8")


class WritableOrthanc(Orthanc):
    def upload(self, filename: str) -> None:
        os.system(
            f"curl -u {self._username}:{self._password} "
            f"-X POST {self._url}/instances --data-binary @{filename}"
        )


def add_image_to_vna(image_filename: str = "test.dcm") -> None:
    path = get_testdata_file("CT_small.dcm")
    ds = dcmread(path)  # type: ignore
    ds.StudyID = STUDY_ID
    ds.PatientID = PATIENT_ID
    ds.save_as(image_filename)

    vna = WritableOrthanc(
        url="http://vna-qr:8042",
        username=env_var("ORTHANC_VNA_USERNAME"),
        password=env_var("ORTHANC_VNA_PASSWORD"),
    )
    vna.upload(image_filename)


def test_image_processing() -> None:

    add_image_to_vna()
    study = ImagingStudy.from_message(message_body)
    orthanc_raw = PIXLRawOrthanc()

    assert not study.exists_in(orthanc_raw)
    process_message(message_body=message_body)
    assert study.exists_in(orthanc_raw)

    # TODO: check time last updated after processing again is not incremented
    # process_message(message_body=message_body)
