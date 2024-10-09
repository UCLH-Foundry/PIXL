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
"""System/E2E test setup"""

# ruff: noqa: C408 dict() makes test data easier to read and write
import os
from collections.abc import Generator
from functools import partial, update_wrapper
from pathlib import Path
from typing import Any

from core.db.models import Base, Image
from core.db.queries import engine
from sqlalchemy import URL, cast, create_engine, not_
from sqlalchemy.orm import sessionmaker

# Setting env variables before loading modules
os.environ["PIXL_DB_HOST"] = "localhost"
os.environ["PIXL_DB_PORT"] = "7001"
os.environ["PIXL_DB_USER"] = "pixl_db_username"
os.environ["PIXL_DB_PASSWORD"] = "pixl_db_password"
os.environ["PIXL_DB_NAME"] = "pixl"

import pytest
import requests
from pytest_pixl.dicom import generate_dicom_dataset
from pytest_pixl.ftpserver import PixlFTPServer
from pytest_pixl.helpers import run_subprocess, wait_for_condition
from pytest_pixl.plugin import FtpHostAddress

pytest_plugins = "pytest_pixl"


@pytest.fixture()
def host_export_root_dir() -> Path:
    """Intermediate export dir as seen from the host"""
    return Path(__file__).parents[1] / "projects" / "exports"


TEST_DIR = Path(__file__).parent
RESOURCES_DIR = TEST_DIR / "resources"
RESOURCES_OMOP_DIR = RESOURCES_DIR / "omop"
RESOURCES_OMOP_DICOMWEB_DIR = RESOURCES_DIR / "omop-dicomweb"


def _upload_to_vna(image_filename: Path) -> None:
    with image_filename.open("rb") as dcm:
        data = dcm.read()
        requests.post(
            "http://localhost:8043/instances",
            auth=("orthanc", "orthanc"),
            data=data,
            timeout=60,
        )


@pytest.fixture(scope="session")
def _populate_vna(tmp_path_factory: pytest.TempPathFactory) -> None:
    dicom_dir = tmp_path_factory.mktemp("dicom_series")
    # more detailed series testing is found in pixl_dcmd tests, but here
    # we just stick an instance to each study, one of which is expected to be propagated through

    def series_instance_uid(offset: int) -> dict[str, str]:
        baseline = "1.3.46.670589.11.38023.5.0.7404.2023012517551898153"
        offset_str = f"{offset:04d}"
        return dict(SeriesInstanceUID=baseline[: -len(offset_str)] + offset_str)

    def sop_instance_uid(offset: int) -> dict[str, str]:
        baseline = "1.3.46.670589.11.38023.5.0.7404.2023012517580650156"
        offset_str = f"{offset:04d}"
        return dict(SOPInstanceUID=baseline[: -len(offset_str)] + offset_str)

    study_1 = dict(
        AccessionNumber="AA12345601",
        PatientID="987654321",
        StudyID="12340001",
        StudyInstanceUID="1.3.6.1.4.1.14519.5.2.1.99.1071.12985477682660597455732044031486",
    )
    study_2 = dict(
        AccessionNumber="AA12345605",
        PatientID="987654321",
        StudyID="12340002",
        StudyInstanceUID="1.2.276.0.7230010.3.1.2.929116473.1.1710754859.579485",
    )

    # Series are also defined by the SeriesInstanceUID and SeriesNumber.
    # SeriesNumber doesn't have to be globally unique, only within a study,
    # however I'm assuming SeriesInstanceUID does. So that must be generated when
    # a series is attached to a study.
    series_0 = dict(SeriesDescription="AP", SeriesNumber=900, Modality="DX")
    series_1 = dict(SeriesDescription="include123", SeriesNumber=901, Modality="DX")
    # excluded by modality filter
    series_exclude_2 = dict(SeriesDescription="exclude123", SeriesNumber=902, Modality="MR")
    # excluded by series description
    series_exclude_3 = dict(SeriesDescription="positioning", SeriesNumber=903, Modality="DX")

    # instances are also defined by the SOPInstanceUID

    # to replace Dicom1.dcm
    instance_0 = dict(**study_1, **series_0, **series_instance_uid(0), **sop_instance_uid(0))

    instance_1 = dict(**study_1, **series_1, **series_instance_uid(1), **sop_instance_uid(1))
    instance_2 = dict(
        **study_1, **series_exclude_2, **series_instance_uid(2), **sop_instance_uid(2)
    )
    instance_3 = dict(
        **study_1, **series_exclude_3, **series_instance_uid(3), **sop_instance_uid(3)
    )
    instance_4 = dict(**study_2, **series_1, **series_instance_uid(4), **sop_instance_uid(4))
    instance_5 = dict(
        **study_2, **series_exclude_3, **series_instance_uid(5), **sop_instance_uid(5)
    )

    _upload_dicom_instance(dicom_dir, **instance_0)
    _upload_dicom_instance(dicom_dir, **instance_1)
    _upload_dicom_instance(dicom_dir, **instance_2)
    _upload_dicom_instance(dicom_dir, **instance_3)
    _upload_dicom_instance(dicom_dir, **instance_4)
    _upload_dicom_instance(dicom_dir, **instance_5)


def _upload_dicom_instance(dicom_dir: Path, **kwargs: Any) -> None:
    ds = generate_dicom_dataset(**kwargs)
    test_dcm_file = (
        dicom_dir
        / f"{kwargs['PatientID']}_{kwargs['AccessionNumber']}_{kwargs['SeriesDescription']}.dcm"
    )
    ds.save_as(str(test_dcm_file), write_like_original=False)
    # I think we can skip writing to disk!
    _upload_to_vna(test_dcm_file)


def wait_for_images_to_be_exported(
    seconds_max: int,
    seconds_interval: int,
    seconds_condition_stays_true_for: int,
    min_studies: int = 2,
) -> None:
    """
    Query pixl DB to ensure that images have been processed and exported.
    If they haven't within the time limit, raise a TimeoutError
    """
    studies: list[Image] = []

    def at_least_n_studies_exported(n_studies: int) -> bool:
        nonlocal studies

        PixlSession = sessionmaker(engine)
        with PixlSession() as session:
            studies = cast(
                list[Image],
                session.query(Image).filter(not_(Image.exported_at.is_(None))).all(),
            )
        return len(studies) >= n_studies

    condition = partial(at_least_n_studies_exported, min_studies)
    update_wrapper(condition, at_least_n_studies_exported)

    def list_studies() -> str:
        return f"Expecting at least {min_studies} studies.\nexported studies: {studies}"

    wait_for_condition(
        condition,
        seconds_max=seconds_max,
        seconds_interval=seconds_interval,
        progress_string_fn=list_studies,
        seconds_condition_stays_true_for=seconds_condition_stays_true_for,
    )


@pytest.fixture(scope="session")
def _setup_pixl_cli(ftps_server: PixlFTPServer, _populate_vna: None) -> Generator:
    """Run pixl populate/start. Cleanup intermediate export dir on exit."""
    run_subprocess(
        ["pixl", "populate", "--num-retries", "0", str(RESOURCES_OMOP_DIR.absolute())],
        TEST_DIR,
        timeout=600,
    )
    # poll here for two minutes to check for imaging to be processed, printing progress
    wait_for_images_to_be_exported(211, 5, 15)
    yield
    run_subprocess(
        [
            "docker",
            "exec",
            "system-test-export-api-1",
            "rm",
            "-r",
            "/run/projects/exports/test-extract-uclh-omop-cdm/",
        ],
        TEST_DIR,
    )


@pytest.fixture(scope="session")
def _setup_pixl_cli_dicomweb(_populate_vna: None) -> Generator:
    """Run pixl populate/start. Cleanup intermediate export dir on exit."""
    run_subprocess(
        ["pixl", "populate", "--num-retries", "0", str(RESOURCES_OMOP_DICOMWEB_DIR.absolute())],
        TEST_DIR,
        timeout=600,
    )
    # poll here for two minutes to check for imaging to be processed, printing progress
    wait_for_images_to_be_exported(211, 5, 15)
    yield
    run_subprocess(
        [
            "docker",
            "exec",
            "system-test-export-api-1",
            "rm",
            "-r",
            "/run/projects/exports/test-extract-uclh-omop-cdm-dicomweb/",
        ],
        TEST_DIR,
    )


@pytest.fixture(scope="session")
def ftp_host_address() -> Any:
    """Run FTP on docker host - docker containers do need to access it"""
    return FtpHostAddress.DOCKERHOST


@pytest.fixture(scope="session")
def _export_patient_data(_setup_pixl_cli) -> None:  # type: ignore [no-untyped-def]
    """
    run pixl export-patient-data. No subsequent wait is needed, because this API call
    is synchronous (whether that is itself wise is another matter).
    """
    run_subprocess(["pixl", "export-patient-data", str(RESOURCES_OMOP_DIR.absolute())], TEST_DIR)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_database() -> Generator:
    """
    Remove the test data from the database so we can re-run the tests.

    If the database is not cleaned, the data will not be exported when the
    tests are re-run, which results in `wait_for_condition` timing out.
    """
    yield
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ["PIXL_DB_USER"],
        password=os.environ["PIXL_DB_PASSWORD"],
        host="localhost",
        port=os.environ["PIXL_DB_PORT"],
        database=os.environ["PIXL_DB_NAME"],
    )
    engine = create_engine(url)
    PixlSession = sessionmaker(engine)
    with PixlSession() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
