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
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from core.omop import OmopExtract
from core.patient_queue.message import Message, deserialise

from pixl_cli._logging import logger
from pixl_cli._utils import string_is_non_empty

# instance of omop extract, can be overriden during testing
extract = OmopExtract()


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

    return [
        deserialise(line) for line in Path.open(filepath).readlines() if string_is_non_empty(line)
    ]


def copy_parquet_return_logfile_fields(parquet_path: Path) -> tuple[str, datetime]:
    """Copy public parquet file to extracts directory, and return fields from logfile"""
    log_file = parquet_path / "extract_summary.json"

    logs = json.load(log_file.open())
    project_name = logs["settings"]["cdm_source_name"]
    omop_es_timestamp = datetime.fromisoformat(logs["datetime"])
    project_name_slug = extract.copy_to_exports(parquet_path, project_name, omop_es_timestamp)
    return project_name_slug, omop_es_timestamp


def messages_from_parquet(
    dir_path: Path, project_name: str, omop_es_timestamp: datetime
) -> list[Message]:
    """
    Reads patient information from parquet files within directory structure
    and transforms that into messages.

    :param dir_path: Path for parquet directory containing private and public
    :param project_name: Name of the project, should be a slug, so it can match the export directory
    :param omop_es_timestamp: Datetime that OMOP ES ran the extract
    files
    """
    public_dir = dir_path / "public"
    private_dir = dir_path / "private"

    cohort_data = _check_and_parse_parquet(private_dir, public_dir)

    expected_col_names = [
        "PrimaryMrn",
        "AccessionNumber",
        "person_id",
        "procedure_date",
        "procedure_occurrence_id",
    ]
    _raise_if_column_names_not_found(cohort_data, expected_col_names)

    (
        mrn_col_name,
        acc_num_col_name,
        _,
        dt_col_name,
        procedure_occurrence_id,
    ) = expected_col_names

    messages = []

    for _, row in cohort_data.iterrows():
        message = Message(
            mrn=row[mrn_col_name],
            accession_number=row[acc_num_col_name],
            study_date=row[dt_col_name],
            procedure_occurrence_id=row[procedure_occurrence_id],
            project_name=project_name,
            omop_es_timestamp=omop_es_timestamp,
        )
        messages.append(message)

    if len(messages) == 0:
        msg = f"Failed to find any messages in {dir_path}"
        raise ValueError(msg)

    logger.info(f"Created {len(messages)} messages from {dir_path}")
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
    return people_procedures.merge(accessions, on="procedure_occurrence_id")


def _raise_if_column_names_not_found(
    cohort_data: pd.DataFrame, expected_col_names: list[str]
) -> None:
    logger.debug(
        f"Checking merged parquet files. Expecting columns to include {expected_col_names}"
    )
    for col in expected_col_names:
        if col not in list(cohort_data.columns):
            msg = (
                f"parquet files are expected to have at least {expected_col_names} as "
                f"column names"
            )
            raise ValueError(msg)