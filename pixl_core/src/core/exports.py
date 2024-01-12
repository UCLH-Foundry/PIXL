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
"""Processing of OMOP parquet files."""
from __future__ import annotations

import logging
import pathlib
import shutil
from typing import TYPE_CHECKING

import slugify

if TYPE_CHECKING:
    import datetime

    import pandas as pd


root_from_install = pathlib.Path(__file__).parents[3]

logger = logging.getLogger(__file__)


class ParquetExport:
    """Exporting Omop and Emap extracts to Parquet files."""

    root_dir: pathlib.Path = root_from_install

    def __init__(self, project_name: str, extract_datetime: datetime.datetime) -> None:
        """
        :param project_name: name of the project
        :param extract_datetime: datetime that the OMOP ES extract was run
        """
        self.export_dir = ParquetExport.root_dir / "exports"
        self.project_slug, self.extract_time_slug = self._get_slugs(project_name, extract_datetime)
        self.export_base = self.export_dir / self.project_slug
        current_extract = self.export_base / "all_extracts" / "omop" / self.extract_time_slug
        self.public_output = current_extract / "public"
        self.radiology_output = current_extract / "radiology"
        self.latest_parent_dir = self.export_base / "latest" / "omop"

    @staticmethod
    def _get_slugs(project_name: str, extract_datetime: datetime.datetime) -> tuple[str, str]:
        """Convert project name and datetime to slugs for writing to filesystem."""
        project_slug = slugify.slugify(project_name)
        extract_time_slug = slugify.slugify(extract_datetime.isoformat())
        return project_slug, extract_time_slug

    def copy_to_exports(self, omop_dir: pathlib.Path) -> str:
        """
        Copy public omop directory as the latest extract for the project.
        Creates directories if they don't already exist.
        :param omop_dir: parent path for omop export, with a "public" subdirectory
        :raises FileNotFoundError: if there is no public subdirectory in `omop_dir`
        :returns str: the project slug, so this can be registered for export to the DSH
        """
        public_input = omop_dir / "public"
        if not public_input.exists():
            msg = f"Could not find public directory in input {omop_dir}"
            raise FileNotFoundError(msg)

        # Make directory for exports if they don't exist
        ParquetExport._mkdir(self.public_output)
        logger.info("Copying public parquet files from %s to %s", omop_dir, self.public_output)

        # Copy extract files, overwriting if it exists
        shutil.copytree(public_input, self.public_output, dirs_exist_ok=True)
        # Make the latest export dir if it doesn't exist

        self._mkdir(self.latest_parent_dir)
        # Symlink this extract to the latest directory
        latest_public = self.latest_parent_dir / "public"
        if latest_public.exists():
            latest_public.unlink()

        latest_public.symlink_to(self.public_output, target_is_directory=True)
        return self.project_slug

    def export_radiology(self, export_df: pd.DataFrame) -> pathlib.Path:
        """Export radiology reports to parquet file"""
        self._mkdir(self.radiology_output)
        parquet_file = self.radiology_output / "radiology.parquet"

        export_df.to_parquet(parquet_file)

        # Make the "latest" export dir if it doesn't exist
        self._mkdir(self.latest_parent_dir)
        # Symlink this report to the latest directory
        latest_parquet_file = self.latest_parent_dir / "radiology.parquet"
        if latest_parquet_file.exists():
            latest_parquet_file.unlink()

        latest_parquet_file.symlink_to(parquet_file, target_is_directory=False)

        return self.radiology_output

    @staticmethod
    def _mkdir(directory: pathlib.Path) -> pathlib.Path:
        directory.mkdir(parents=True, exist_ok=True)
        return directory