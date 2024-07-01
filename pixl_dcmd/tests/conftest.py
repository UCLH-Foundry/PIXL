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
"""CLI testing fixtures."""

from __future__ import annotations

import datetime
import os
import pathlib
import tempfile
from collections.abc import Generator
from typing import Optional

import pytest
import pytest_pixl.dicom
import requests
from core.db.models import Base, Extract, Image
from core.dicom_tags import (
    DICOM_TAG_PROJECT_NAME,
    add_private_tag,
)
from pydicom import Dataset
from pytest_pixl.dicom import generate_dicom_dataset
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ["SALT_VALUE"] = "test_salt"
os.environ["HASHER_API_AZ_NAME"] = "test_hash_API"
os.environ["HASHER_API_PORT"] = "test_hash_API_port"
os.environ["TIME_OFFSET"] = "5"
os.environ["PROJECT_CONFIGS_DIR"] = str(
    pathlib.Path(__file__).parents[2] / "projects/configs"
)

STUDY_DATE = datetime.date.fromisoformat("2023-01-01")
TEST_PROJECT_SLUG = "test-extract-uclh-omop-cdm"

EXPORTED_MRN = "987654321"
EXPORTED_ACCESSION_NUMBER = "AA12345601"


@pytest.fixture()
def rows_in_session(db_session) -> Session:
    """Insert a test row for each table, returning the session for use in tests."""
    extract = Extract(slug=TEST_PROJECT_SLUG)

    image_exported = Image(
        accession_number=EXPORTED_ACCESSION_NUMBER,
        study_date=STUDY_DATE,
        mrn=EXPORTED_MRN,
        extract=extract,
        exported_at=datetime.datetime.now(tz=datetime.timezone.utc),
    )
    image_not_exported = Image(
        accession_number="AA12345605",
        study_date=STUDY_DATE,
        mrn="987654321",
        extract=extract,
    )
    with db_session:
        db_session.add_all([extract, image_exported, image_not_exported])
        db_session.commit()

    return db_session


@pytest.fixture()
def row_for_dicom_testing(db_session) -> Session:
    """Insert a test row for each table, returning the session for use in tests."""
    extract = Extract(slug=TEST_PROJECT_SLUG)

    image_not_exported = Image(
        accession_number="BB01234567",
        study_date=STUDY_DATE,
        mrn="ID123456",
        extract=extract,
    )
    with db_session:
        db_session.add_all([extract, image_not_exported])
        db_session.commit()

    return db_session


@pytest.fixture()
def directory_of_mri_dicoms() -> Generator[pathlib.Path, None, None]:
    """Directory containing MRI DICOMs suitable for testing."""
    with tempfile.TemporaryDirectory() as td:
        pytest_pixl.dicom.write_volume(td + "/{slice}.dcm")
        td_path = pathlib.Path(td)
        yield td_path


@pytest.fixture(scope="module")
def monkeymodule():
    """Module level monkey patch."""
    from _pytest.monkeypatch import MonkeyPatch

    monkeypatch = MonkeyPatch()
    yield monkeypatch
    monkeypatch.undo()


@pytest.fixture(autouse=True, scope="module")
def db_engine(monkeymodule) -> Generator[Engine, None, None]:
    """
    Patches the database engine with an in memory database

    :returns Engine: Engine for use in other setup fixtures
    """
    # SQLite doesnt support schemas, so remove pixl schema from engine options
    execution_options = {"schema_translate_map": {"pipeline": None}}
    engine = create_engine(
        "sqlite:///:memory:",
        execution_options=execution_options,
        echo=True,
        echo_pool="debug",
        future=True,
    )
    monkeymodule.setattr("pixl_dcmd._database.engine", engine)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Creates a session for interacting with an in memory database.

    Will remove any data from database in setup

    :returns Session: Session for use in other setup fixtures.

    """
    InMemorySession = sessionmaker(db_engine)
    with InMemorySession() as session:
        # sqlite with sqlalchemy doesn't rollback, so manually deleting all database entities
        session.query(Image).delete()
        session.query(Extract).delete()
        yield session
    session.close()


class MockResponse(object):
    def __init__(self, content: str) -> None:
        self.status_code = 200
        self.content = "-".join(list(content)).encode("utf-8")
        self.text = self.content.decode("utf-8")


# monkeypatched requests.get moved to a fixture
@pytest.fixture(autouse=True)
def mock_response(monkeypatch):
    """Requests.get() mocked to return MockedResponse built from input."""

    def mock_get(input: str, params: dict):
        return MockResponse(params["message"])

    monkeypatch.setattr(requests, "get", mock_get)


@pytest.fixture()
def mock_header_record_path(monkeypatch, tmpdir):
    """Return path to temporary directory instead of getting value from envvar."""

    def mock_get(key, default) -> Optional[str]:
        if key == "ORTHANC_RAW_HEADER_LOG_PATH":
            return str(tmpdir.join("test_header_log.csv"))
        return os.environ.get(key, default)

    monkeypatch.setattr(os.environ, "get", mock_get)


@pytest.fixture()
def vanilla_dicom_image(row_for_dicom_testing) -> Dataset:
    """
    A DICOM image with diffusion data to test the anonymisation process.
    Private tags were added to match the tag operations defined in the project config, so we can
    test whether the anonymisation process works as expected when defining overrides.
    The row_for_dicom_testing dependency is to make sure the database is populated with the
    project slug, which is used to anonymise the DICOM image.
    """
    ds = generate_dicom_dataset(Modality="DX")

    # Make sure the project name tag is added for anonymisation to work
    add_private_tag(ds, DICOM_TAG_PROJECT_NAME)
    # Update the project name tag to a known value
    block = ds.private_block(
        DICOM_TAG_PROJECT_NAME.group_id, DICOM_TAG_PROJECT_NAME.creator_string
    )
    ds[block.get_tag(DICOM_TAG_PROJECT_NAME.offset_id)].value = TEST_PROJECT_SLUG

    return ds
