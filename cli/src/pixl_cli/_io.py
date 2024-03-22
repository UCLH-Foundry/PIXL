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
"""Reading and writing files from PIXL CLI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from core.exports import ParquetExport
from core.patient_queue.message import Message, deserialise

from pixl_cli._logging import logger
from pixl_cli._utils import string_is_non_empty

# The export root dir from the point of view of the docker host (which is where the CLI runs)
# For the view from inside, see pixl_ehr/main.py: EHR_EXPORT_ROOT_DIR
HOST_EXPORT_ROOT_DIR = Path(__file__).parents[3] / "projects" / "exports"


def messages_from_state_file(filepath: Path) -> list[Message]:
    """
    Return messages from a state file path

    :param filepath: Path for state file to be read
    :return: A list of Message objects containing all the messages from the state file
    """
    logger.info(f"Creating messages from {filepath}")
    if not filepath.exists():
        raise FileNotFoundError
    if filepath.suffix != ".state":
        msg = f"Invalid file suffix for {filepath}. Expected .state"
        raise ValueError(msg)

    return [deserialise(line) for line in filepath.open().readlines() if string_is_non_empty(line)]


def project_info(resources_path: Path) -> tuple[str, datetime]:
    """
    Get the project name and extract timestamp from the extract summary log file.
    :param resources_path: path to the input resources
    """
    log_file = resources_path / "extract_summary.json"
    logs = json.load(log_file.open())
    project_name = logs["settings"]["cdm_source_name"]
    extract_generated_timestamp = datetime.fromisoformat(logs["datetime"])
    return project_name, extract_generated_timestamp


def copy_parquet_return_logfile_fields(resources_path: Path) -> tuple[str, datetime]:
    """Copy public parquet file to extracts directory, and return fields from logfile"""
    project_name, extract_generated_timestamp = project_info(resources_path)
    extract = ParquetExport(project_name, extract_generated_timestamp, HOST_EXPORT_ROOT_DIR)
    project_name_slug = extract.copy_to_exports(resources_path)
    return project_name_slug, extract_generated_timestamp


def messages_from_csv(filepath: Path) -> list[Message]:
    """
    Reads patient information from CSV and transforms that into messages.
    :param filepath: Path for CSV file to be read
    """
    expected_col_names = [
        "procedure_id",
        "mrn",
        "accession_number",
        "project_name",
        "extract_generated_timestamp",
        "study_date",
    ]

    # First line is column names
    messages_df = pd.read_csv(filepath, header=0, dtype=str)
    # Parse non string columns
    messages_df["procedure_id"] = messages_df["procedure_id"].astype(int)
    messages_df["study_date"] = pd.to_datetime(
        messages_df["study_date"], format="%Y-%m-%d", errors="raise"
    ).dt.date
    messages_df["extract_generated_timestamp"] = pd.to_datetime(
        messages_df["extract_generated_timestamp"],
        format="%Y-%m-%dT%H:%M:%SZ",
        errors="raise",
        utc=True,
    )

    _raise_if_column_names_not_found(messages_df, expected_col_names)

    (
        procedure_id_col_name,
        mrn_col_name,
        acc_num_col_name,
        project_col_name,
        extract_col_name,
        dt_col_name,
    ) = expected_col_names

    messages = []
    for _, row in messages_df.iterrows():
        message = Message(
            mrn=row[mrn_col_name],
            accession_number=row[acc_num_col_name],
            study_date=row[dt_col_name],
            procedure_occurrence_id=row[procedure_id_col_name],
            project_name=row[project_col_name],
            extract_generated_timestamp=row[extract_col_name].to_pydatetime(),
        )
        messages.append(message)

    if len(messages) == 0:
        msg = f"Failed to find any messages in {filepath}"
        raise ValueError(msg)

    logger.info(f"Created {len(messages)} messages from {filepath}")
    return messages


def messages_from_parquet(
    dir_path: Path, project_name: str, extract_generated_timestamp: datetime
) -> list[Message]:
    """
    Reads patient information from parquet files within directory structure
    and transforms that into messages.

    :param dir_path: Path for parquet directory containing private and public
    :param project_name: Name of the project, should be a slug, so it can match the export directory
    :param extract_generated_timestamp: Datetime that OMOP ES ran the extract
    files
    """
    public_dir = dir_path / "public"
    private_dir = dir_path / "private"

    cohort_data = _check_and_parse_parquet(private_dir, public_dir)

    map_column_to_message_params = {
        "mrn": "PrimaryMrn",
        "accession_number": "AccessionNumber",
        "study_date": "procedure_date",
        "procedure_occurrence_id": "procedure_occurrence_id",
    }

    _raise_if_column_names_not_found(cohort_data, list(map_column_to_message_params.values()))

    messages = []

    for _, row in cohort_data.iterrows():
        message_params = {
            param: row[column] for param, column in map_column_to_message_params.items()
        }
        message = Message(
            project_name=project_name,
            extract_generated_timestamp=extract_generated_timestamp,
            **message_params,
        )
        messages.append(message)

    if len(messages) == 0:
        msg = f"Failed to find any messages in {dir_path}"
        raise ValueError(msg)

    logger.info(f"Created {len(messages)} messages from {dir_path}")
    return messages


def messages_from_parquet_file(
    file_path: Path,
    project_name: str,
    timestamp: datetime,
) -> list[Message]:
    """
    Reads patient information from a parquet file and transforms that into messages.

    :param file_path: Path for parquet file
    """
    cohort_data = pd.read_parquet(file_path)

    map_column_to_message_params = {
        "mrn": "PrimaryMrn",
        "accession_number": "AccessionNumber",
        "study_date": "procedure_date",
        "procedure_occurrence_id": "procedure_occurrence_id",
    }

    _raise_if_column_names_not_found(cohort_data, list(map_column_to_message_params.values()))

    messages = []

    for _, row in cohort_data.iterrows():
        message_params = {
            param: row[column] for param, column in map_column_to_message_params.items()
        }
        message = Message(project_name=project_name, timestamp=timestamp, **message_params)
        messages.append(message)

    if len(messages) == 0:
        msg = f"Failed to find any messages in {file_path}"
        raise ValueError(msg)

    logger.info(f"Created {len(messages)} messages from {file_path}")
    return messages


def _check_and_parse_parquet(private_dir: Path, public_dir: Path) -> pd.DataFrame:
    for d in [public_dir, private_dir]:
        if not d.is_dir():
            err_str = f"{d} must exist and be a directory"
            raise NotADirectoryError(err_str)

    # MRN in people.PrimaryMrn:
    people = pd.read_parquet(private_dir / "PERSON_LINKS.parquet")
    # accession number in accessions.AccessionNumber
    accessions = pd.read_parquet(private_dir / "PROCEDURE_OCCURRENCE_LINKS.parquet")
    # study_date is in procedure.procedure_date
    procedure = pd.read_parquet(public_dir / "PROCEDURE_OCCURRENCE.parquet")

    # joining data together
    people_procedures = people.merge(procedure, on="person_id")
    people_procedures_accessions = people_procedures.merge(accessions, on="procedure_occurrence_id")
    return people_procedures_accessions[~people_procedures_accessions["AccessionNumber"].isna()]


def _raise_if_column_names_not_found(
    cohort_data: pd.DataFrame, expected_col_names: list[str]
) -> None:
    logger.debug(
        f"Checking merged parquet files. Expecting columns to include {expected_col_names}"
    )
    for col in expected_col_names:
        if col not in list(cohort_data.columns):
            msg = (
                f"Export specification files are expected to have at least {expected_col_names} as "
                f"column names"
            )
            raise ValueError(msg)
