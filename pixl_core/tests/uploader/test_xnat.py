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
"""Test functionality to upload files to an XNAT instance."""

import io
import os
from collections.abc import Generator
from pathlib import Path

import pytest
import xnat
import xnat4tests
from core.uploader._orthanc import StudyTags
from core.uploader._xnat import XNATUploader

TEST_DIR = Path(__file__).parents[1]


class MockXNATUploader(XNATUploader):
    """Mock XNATUploader for testing."""

    def __init__(self) -> None:
        """Initialise the mock uploader with hardcoded values for FTPS config."""
        self.host = os.environ["XNAT_HOST"]
        self.user = os.environ["XNAT_USER_NAME"]
        self.password = os.environ["XNAT_PASSWORD"]
        self.port = os.environ["XNAT_PORT"]
        self.url = f"http://{self.host}:{self.port}"


@pytest.fixture()
def xnat_uploader() -> MockXNATUploader:
    """Return a MockXNATUploader object."""
    return MockXNATUploader()


@pytest.fixture()
def zip_content() -> Generator:
    """Directory containing the test DICOMs for uploading to the XNAT instance."""
    test_zip_file = TEST_DIR / "data" / "dicom_series.zip"
    with test_zip_file.open("rb") as file_content:
        yield io.BytesIO(file_content.read())


@pytest.fixture(scope="session")
def xnat_study_tags() -> StudyTags:
    """Return a StudyTags object for the study to be uploaded to XNAT."""
    return StudyTags(
        pseudo_anon_image_id="1.3.6.1.4.1.14519.5.2.1.99.1071.12985477682660597455732044031486",
        project_slug="some-project-slug",
        patient_id="987654321",
    )


@pytest.fixture(scope="session")
def xnat_server(xnat_study_tags) -> Generator:
    """Start the XNAT server."""
    config = xnat4tests.Config(
        xnat_port=os.environ["XNAT_PORT"],
        docker_host=os.environ["XNAT_HOST"],
        build_args={
            "xnat_version": "1.8.10.1",
        },
    )
    xnat4tests.start_xnat(config)

    # Create the project as well as a non-admin user to perform the upload
    with xnat.connect(
        server=config.xnat_uri,
        user="admin",
        password="admin",  # noqa: S106
    ) as session:
        session.post(
            path="/xapi/users/",
            json=dict(  # noqa: C408
                admin=False,
                username=os.environ["XNAT_USER_NAME"],
                password=os.environ["XNAT_PASSWORD"],
                firstName="pixl",
                lastName="uploader",
                email="pixl-uploader@pixl",
                verified=True,
                enabled=True,
            ),
            headers={"Content-Type": "application/json"},
            accepted_status=[201],
        )

        # XNAT requires project metadata to be uploaded as XML
        with (TEST_DIR / "data" / "xnat_project.xml").open() as file:
            project_xml = file.read()
        session.post(
            path="/data/projects",
            data=project_xml,
            headers={"Content-Type": "application/xml"},
            accepted_status=[200],
        )

        session.put(
            path=f"/data/projects/{xnat_study_tags.project_slug}/users/Owners/pixl",
            accepted_status=[200],
        )

    yield config.xnat_uri
    xnat4tests.stop_xnat(config)


@pytest.mark.usefixtures("xnat_server")
def test_upload_to_xnat(zip_content, xnat_uploader, xnat_study_tags) -> None:
    """Tests that DICOM image can be uploaded to the correct location"""
    xnat_uploader.upload_to_xnat(
        zip_content=zip_content,
        study_tags=xnat_study_tags,
    )

    with xnat.connect(
        server=xnat_uploader.url,
        user=xnat_uploader.user,
        password=xnat_uploader.password,
    ) as session:
        assert xnat_study_tags.project_slug in session.projects
        project = session.projects[xnat_study_tags.project_slug]

        assert xnat_study_tags.patient_id in project.subjects
        subject = project.subjects[xnat_study_tags.patient_id]

        assert len(subject.experiments) == 1
        experiment = subject.experiments[0]
        assert experiment.label == xnat_study_tags.pseudo_anon_image_id.replace(".", "_")
        assert len(experiment.scans) == 2
