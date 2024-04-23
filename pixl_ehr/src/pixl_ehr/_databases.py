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
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pandas as pd
import psycopg2 as pypg
from decouple import config

logger = logging.getLogger("uvicorn")

if TYPE_CHECKING:
    from datetime import datetime

    from pixl_ehr._processing import PatientEHRData
    from pixl_ehr._queries import SQLQuery


class Database:
    """Fake database wrapper"""

    def __init__(  # noqa: PLR0913 Too many arguments in function definition
        self,
        db_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = 4567,
    ) -> None:
        connection_string = (
            f"dbname={db_name} user={username} password={password} host={host} port={port}"
        )
        self._connection = pypg.connect(connection_string)
        self._cursor = self._connection.cursor()


class QueryableDatabase(Database):
    def execute(self, query: SQLQuery) -> Optional[tuple]:
        """Execute an sql query"""
        # logger.debug(f"Running query: \n"
        #             f"{self._cursor.mogrify(str(query), vars=query.values).decode()}")

        self._cursor.execute(query=str(query), vars=query.values)
        row = self._cursor.fetchone()
        return None if row is None else tuple(row)

    def execute_or_raise(self, query: SQLQuery, error_str: str = "Failed") -> tuple:
        result = self.execute(query)

        if result is None:
            raise RuntimeError(error_str)

        return result


class WriteableDatabase(Database):
    def persist(self, template: str, values: list) -> None:
        """Execute an sql query"""
        self._cursor.execute(template, vars=values)
        self._connection.commit()


class EMAPStar(QueryableDatabase):
    def __init__(self) -> None:
        super().__init__(
            db_name=config("EMAP_UDS_NAME"),
            username=config("EMAP_UDS_USER"),
            password=config("EMAP_UDS_PASSWORD"),
            host=config("EMAP_UDS_HOST"),
            port=config("EMAP_UDS_PORT", int),
        )

    def __repr__(self) -> str:
        return "EMAPStarDatabase"


class PIXLDatabase(WriteableDatabase, QueryableDatabase):
    def __init__(self) -> None:
        super().__init__(
            db_name=config("PIXL_DB_NAME"),
            username=config("PIXL_DB_USER"),
            password=config("PIXL_DB_PASSWORD"),
            host=config("PIXL_DB_HOST"),
            port=config("PIXL_DB_PORT", int),
        )

    def __repr__(self) -> str:
        return "PIXLDatabase"

    def to_csv(self, schema_name: str, table_name: str, filename: str) -> None:
        """Extract the content of a table within a schema to a csv file and save it"""
        query = f"COPY (SELECT * FROM {schema_name}.{table_name}) TO STDOUT WITH CSV HEADER"

        with Path(filename, "w").open() as file:
            self._cursor.copy_expert(query, file)

    def contains(self, data: PatientEHRData) -> bool:
        """Does the database contain a set of data already?"""
        query = "SELECT * FROM emap_data.ehr_raw WHERE mrn = %s and accession_number = %s"
        self._cursor.execute(query=str(query), vars=[data.mrn, data.accession_number])
        return self._cursor.fetchone() is not None

    def get_radiology_reports(
        self, slugified_project_name: str, extract_datetime: datetime
    ) -> pd.DataFrame:
        """Get all radiology reports for a given study."""
        query = (
            "SELECT image_identifier, procedure_occurrence_id, xray_report FROM emap_data.ehr_anon "
            "WHERE project_name = %s AND extract_datetime = %s"
        )
        self._cursor.execute(query=str(query), vars=[slugified_project_name, extract_datetime])
        anon_data = self._cursor.fetchall()
        parquet_header_names = ["image_identifier", "procedure_occurrence_id", "image_report"]
        return pd.DataFrame(anon_data, columns=parquet_header_names)