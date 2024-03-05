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

import os
from pathlib import Path

import pytest
from core.db.models import Base, Extract, Image
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ["PROJECT_CONFIGS_DIR"] = str(Path(__file__).parents[2] / "projects/configs")

# Set the necessary environment variables
os.environ["PIXL_EHR_API_HOST"] = "localhost"
os.environ["PIXL_EHR_API_RATE"] = "1"
os.environ["PIXL_EHR_API_PORT"] = "7006"

os.environ["PIXL_IMAGING_API_HOST"] = "localhost"
os.environ["PIXL_IMAGING_API_RATE"] = "1"
os.environ["PIXL_IMAGING_API_PORT"] = "7007"

os.environ["RABBITMQ_HOST"] = "localhost"
os.environ["RABBITMQ_USERNAME"] = "rabbitmq_username"
os.environ["RABBITMQ_PASSWORD"] = "rabbitmq_password"  # noqa: S105
os.environ["RABBITMQ_PORT"] = "7008"

os.environ["PIXL_DB_USER"] = "pixl_db_username"
os.environ["PIXL_DB_PASSWORD"] = "pixl_db_password"  # noqa: S105
os.environ["POSTGRES_HOST"] = "locahost"
os.environ["POSTGRES_PORT"] = "7001"
os.environ["PIXL_DB_NAME"] = "pixl"


@pytest.fixture(autouse=True)
def export_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Tmp dir to for tests to extract to."""
    export_dir = tmp_path_factory.mktemp("export_base") / "exports"
    export_dir.mkdir()
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
def db_session(db_engine) -> Session:
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
