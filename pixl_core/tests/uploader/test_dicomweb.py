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
"""Test functionality to upload files to a DICOMWeb endpoint."""

import os

import pytest
import requests
from core.uploader import DicomWebUploader  # type: ignore [import-untyped]
from decouple import config  # type: ignore [import-untyped]

# TODO: move these to conftest.py
os.environ["ORTHANC_USERNAME"] = "orthanc"
os.environ["ORTHANC_PASSWORD"] = "orthanc"  # noqa: S105, hardcoded password
os.environ["DICOM_ENDPOINT_NAME"] = "test"

ORTHANC_URL = "http://localhost:8042"
DICOM_ENDPOINT_NAME = config("DICOM_ENDPOINT_NAME")
ORTHANC_USERNAME = config("ORTHANC_USERNAME")
ORTHANC_PASSWORD = config("ORTHANC_PASSWORD")


class MockDicomWebUploader(DicomWebUploader):
    """Mock DicomWebUploader for testing."""

    def __init__(self) -> None:
        """Initialise the mock uploader."""
        self.host = ORTHANC_URL
        self.username = ORTHANC_USERNAME
        self.password = ORTHANC_PASSWORD
        self.endpoint_name = DICOM_ENDPOINT_NAME


@pytest.fixture()
def dicomweb_uploader() -> MockDicomWebUploader:
    """Fixture to return a mock DicomWebUploader."""
    return MockDicomWebUploader()


def test_upload_dicom_image(
    test_zip_content, not_yet_exported_dicom_image, dicomweb_uploader
) -> None:
    """Tests that DICOM image can be uploaded to a DICOMWeb server"""
    # ARRANGE
    # Get the pseudo identifier from the test image
    pseudo_anon_id = not_yet_exported_dicom_image.hashed_identifier
    project_slug = "some-project-slug"

    # ACT
    dicomweb_uploader.upload_dicom_image(test_zip_content, pseudo_anon_id, project_slug)

    # ASSERT
    url = ORTHANC_URL + "/dicom-web/servers/" + DICOM_ENDPOINT_NAME + "/stow"
    response = requests.get(url, auth=(ORTHANC_USERNAME, ORTHANC_PASSWORD), timeout=30)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["ID"] == pseudo_anon_id
