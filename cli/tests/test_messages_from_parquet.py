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

from pathlib import Path

from pixl_cli.main import messages_from_parquet


def test_messages_from_parquet(resources: Path) -> None:
    """
    Test that the messages are as expected, given the test parquet files.
    The test data doesn't have any "difficult" cases in it, eg. people without procedures.
    """
    omop_parquet_dir = resources / "omop"
    messages = messages_from_parquet(omop_parquet_dir)
    expected_messages = [
        b'{"mrn": "12345678", "accession_number": "12345678", "study_datetime": "2021-07-01", '
        b'"procedure_occurrence_id": 1}',
        b'{"mrn": "12345678", "accession_number": "ABC1234567", "study_datetime": "2021-07-01", '
        b'"procedure_occurrence_id": 2}',
        b'{"mrn": "987654321", "accession_number": "ABC1234560", "study_datetime": "2020-05-01", '
        b'"procedure_occurrence_id": 3}',
        b'{"mrn": "5020765", "accession_number": "MIG0234560", "study_datetime": "2015-05-01", '
        b'"procedure_occurrence_id": 4}',
    ]

    assert messages == expected_messages
