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
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from core.db.models import Base, Extract, Image
from core.patient_queue.message import Message
from core.patient_queue.producer import PixlProducer
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from collections.abc import Generator
    from unittest.mock import Mock


# Load environment variables from test .env file
with (Path(__file__).parents[2] / "test/.env").open() as f:
    for line in f.readlines():
        if "=" in line:
            key, value = line.strip().split("=")
            os.environ[key] = value

# Set the remaining environment variables
os.environ["PROJECT_CONFIGS_DIR"] = str(Path(__file__).parents[2] / "projects/configs")

os.environ["EXPORT_AZ_CLIENT_ID"] = "export client id"
os.environ["EXPORT_AZ_CLIENT_PASSWORD"] = "export client password"
os.environ["EXPORT_AZ_TENANT_ID"] = "export tenant id"
os.environ["EXPORT_AZ_KEY_VAULT_NAME"] = "export key vault name"

os.environ["HASHER_API_AZ_CLIENT_ID"] = "hasher client id"
os.environ["HASHER_API_AZ_CLIENT_PASSWORD"] = "hasher client password"
os.environ["HASHER_API_AZ_TENANT_ID"] = "hasher tenant id"
os.environ["HASHER_API_AZ_KEY_VAULT_NAME"] = "hasher key vault name"

os.environ["ORTHANC_RAW_JOB_HISTORY_SIZE"] = "100"
os.environ["ORTHANC_CONCURRENT_JOBS"] = "20"

os.environ["AZ_DICOM_ENDPOINT_NAME"] = "dicom endpoint name"
os.environ["AZ_DICOM_ENDPOINT_URL"] = "dicom endpoint url"
os.environ["AZ_DICOM_ENDPOINT_TOKEN"] = "dicom endpoint token"
os.environ["AZ_DICOM_ENDPOINT_CLIENT_ID"] = "dicom endpoint client id"
os.environ["AZ_DICOM_ENDPOINT_CLIENT_SECRET"] = "dicom endpoint client secret"
os.environ["AZ_DICOM_ENDPOINT_TENANT_ID"] = "dicom endpoint tenant id"

os.environ["TZ"] = "Europe/London"


@pytest.fixture(autouse=True)
def export_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Tmp dir for tests to extract to."""
    export_dir = tmp_path_factory.mktemp("export_base") / "projects" / "exports"
    export_dir.mkdir(parents=True)
    return export_dir


@pytest.fixture(scope="module")
def monkeymodule():
    """Module level monkey patch."""
    from _pytest.monkeypatch import MonkeyPatch

    monkeypatch = MonkeyPatch()
    yield monkeypatch
    monkeypatch.undo()


@pytest.fixture(autouse=True, scope="module")
def db_engine(monkeymodule) -> Engine:
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
    monkeymodule.setattr("pixl_cli._database.engine", engine)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine) -> Generator[Session]:
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


STUDY_DATE = datetime.date.fromisoformat("2023-01-01")


def _make_message(
    project_name: str,
    accession_number: str,
    mrn: str,
    study_uid: str,
) -> Message:
    return Message(
        project_name=project_name,
        accession_number=accession_number,
        mrn=mrn,
        study_uid=study_uid,
        study_date=STUDY_DATE,
        procedure_occurrence_id=1,
        extract_generated_timestamp=datetime.datetime.now(tz=ZoneInfo(os.environ["TZ"])),
    )


@pytest.fixture()
def example_messages() -> list[Message]:
    """Test input data."""
    return [
        _make_message(
            project_name="i-am-a-project", accession_number="123", mrn="mrn", study_uid="1.2.3"
        ),
        _make_message(
            project_name="i-am-a-project", accession_number="234", mrn="mrn", study_uid="2.3.4"
        ),
        _make_message(
            project_name="i-am-a-project", accession_number="345", mrn="mrn", study_uid="3.4.5"
        ),
    ]


@pytest.fixture()
def example_messages_df(example_messages):
    """Test input data in a DataFrame."""
    messages_df = pd.DataFrame.from_records([vars(im) for im in example_messages])
    messages_df["pseudo_patient_id"] = None
    return messages_df


@pytest.fixture()
def example_messages_multiple_projects() -> list[Message]:
    """Test input data."""
    return [
        _make_message(
            project_name="i-am-a-project", accession_number="123", mrn="mrn", study_uid="1.2.3"
        ),
        _make_message(
            project_name="i-am-a-project", accession_number="234", mrn="mrn", study_uid="2.3.4"
        ),
        _make_message(
            project_name="i-am-a-project", accession_number="345", mrn="mrn", study_uid="3.4.5"
        ),
        _make_message(
            project_name="i-am-another-project",
            accession_number="123",
            mrn="mrn",
            study_uid="1.2.3",
        ),
        _make_message(
            project_name="i-am-another-project",
            accession_number="234",
            mrn="mrn",
            study_uid="2.3.4",
        ),
        _make_message(
            project_name="i-am-another-project",
            accession_number="345",
            mrn="mrn",
            study_uid="3.4.5",
        ),
    ]


@pytest.fixture()
def example_messages_multiple_projects_df(example_messages_multiple_projects) -> pd.DataFrame:
    """Test input data."""
    messages_df = pd.DataFrame.from_records([vars(im) for im in example_messages_multiple_projects])
    messages_df["pseudo_patient_id"] = None
    return messages_df


@pytest.fixture()
def rows_in_session(db_session) -> Session:
    """Insert a test row for each table, returning the session for use in tests."""
    extract = Extract(slug="i-am-a-project")

    image_exported = Image(
        accession_number="123",
        study_date=STUDY_DATE,
        mrn="mrn",
        study_uid="1.2.3",
        extract=extract,
        extract_id=extract.extract_id,
        exported_at=datetime.datetime.now(ZoneInfo(os.environ["TZ"])),
    )
    image_not_exported = Image(
        accession_number="234",
        study_date=STUDY_DATE,
        mrn="mrn",
        study_uid="2.3.4",
        extract=extract,
        extract_id=extract.extract_id,
    )
    with db_session:
        db_session.add_all([extract, image_exported, image_not_exported])
        db_session.commit()

    return db_session


@pytest.fixture()
def mock_publisher(mocker) -> Generator[Mock, None, None]:
    """Patched publisher that does nothing, returns MagicMock of the publish method."""
    mocker.patch.object(PixlProducer, "__init__", return_value=None)
    mocker.patch.object(PixlProducer, "__enter__", return_value=PixlProducer)
    mocker.patch.object(PixlProducer, "__exit__")
    return mocker.patch.object(PixlProducer, "publish")
