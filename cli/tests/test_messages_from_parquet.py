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
"""Unit tests for reading cohorts from parquet files."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core.patient_queue.message import Message
from pixl_cli._io import (
    copy_parquet_return_logfile_fields,
    messages_from_csv,
    messages_from_parquet,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_messages_from_csv(omop_resources: Path) -> None:
    """
    Given a csv with a single dataset.
    When the messages are generated from the directory
    Then one message should be generated
    """
    # Arrange
    test_csv = omop_resources / "test.csv"
    # Act
    messages = messages_from_csv(test_csv)
    # Assert
    assert all(isinstance(msg, Message) for msg in messages)

    expected_messages = [
        Message(
            mrn="patient_identifier",
            accession_number="123456789",
            study_date=datetime.date.fromisoformat("2022-01-01"),
            procedure_occurrence_id=0,
            project_name="ms-pinpoint-test",
            extract_generated_timestamp=datetime.datetime.fromisoformat("2023-01-01T00:01:00Z"),
        ),
    ]
    assert messages == expected_messages


def test_messages_from_parquet(omop_resources: Path) -> None:
    """
    Given a valid OMOP ES extract with 4 procedures, two of which are x-rays.
    When the messages are generated from the directory and the output of logfile parsing
    Then two messages should be generated
    """
    # Arrange
    omop_parquet_dir = omop_resources / "omop"
    project_name, omop_es_datetime = copy_parquet_return_logfile_fields(omop_parquet_dir)
    # Act
    messages = messages_from_parquet(omop_parquet_dir, project_name, omop_es_datetime)
    # Assert
    assert all(isinstance(msg, Message) for msg in messages)

    expected_messages = [
        Message(
            mrn="987654321",
            accession_number="AA12345601",
            study_date=datetime.date.fromisoformat("2020-05-23"),
            procedure_occurrence_id=4,
            project_name="test-extract-uclh-omop-cdm",
            extract_generated_timestamp=datetime.datetime.fromisoformat("2023-12-07T14:08:58"),
        ),
        Message(
            mrn="987654321",
            accession_number="AA12345605",
            study_date=datetime.date.fromisoformat("2020-05-23"),
            procedure_occurrence_id=5,
            project_name="test-extract-uclh-omop-cdm",
            extract_generated_timestamp=datetime.datetime.fromisoformat("2023-12-07T14:08:58"),
        ),
    ]

    assert messages == expected_messages
