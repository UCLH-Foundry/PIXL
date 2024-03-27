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
"""Replacement for the 'interesting' bits of the system/E2E test"""

import logging
from pathlib import Path

import pydicom
import pytest
from core.dicom_tags import DICOM_TAG_PROJECT_NAME
from pytest_pixl.helpers import run_subprocess, wait_for_condition

pytest_plugins = "pytest_pixl"


class TestFtpsUpload:
    """tests adapted from ./scripts/check_ftps_upload.py"""

    @pytest.fixture(scope="class", autouse=True)
    def _setup(self, ftps_server) -> None:
        """Shared test data for the two different kinds of FTP upload test"""
        TestFtpsUpload.ftp_home_dir = ftps_server.home_dir
        logging.info("ftp home dir: %s", TestFtpsUpload.ftp_home_dir)

        TestFtpsUpload.project_slug = "test-extract-uclh-omop-cdm"
        TestFtpsUpload.extract_time_slug = "2023-12-07t14-08-58"

        TestFtpsUpload.expected_output_dir = (
            TestFtpsUpload.ftp_home_dir / TestFtpsUpload.project_slug
        )
        TestFtpsUpload.expected_public_parquet_dir = (
            TestFtpsUpload.expected_output_dir / TestFtpsUpload.extract_time_slug / "parquet"
        )
        logging.info("expected output dir: %s", TestFtpsUpload.expected_output_dir)
        logging.info("expected parquet files dir: %s", TestFtpsUpload.expected_public_parquet_dir)
        # No cleanup of ftp uploads needed because it's in a temp dir

    @pytest.mark.usefixtures("_extract_radiology_reports")
    def test_ftps_parquet_upload(self):
        """The copied parquet files"""
        assert TestFtpsUpload.expected_public_parquet_dir.exists()

        assert (
            TestFtpsUpload.expected_public_parquet_dir
            / "omop"
            / "public"
            / "PROCEDURE_OCCURRENCE.parquet"
        ).exists()
        assert (
            TestFtpsUpload.expected_public_parquet_dir / "radiology" / "radiology.parquet"
        ).exists()

    @pytest.mark.usefixtures("_extract_radiology_reports")
    def test_ftps_dicom_upload(self, tmp_path_factory):
        """Test whether DICOM images have been uploaded"""
        zip_files = []

        def zip_file_list() -> str:
            return f"zip files found: {zip_files}"

        def two_zip_files_present() -> bool:
            nonlocal zip_files
            zip_files = list(TestFtpsUpload.expected_output_dir.glob("*.zip"))
            # We expect 2 DICOM image studies to be uploaded
            return len(zip_files) == 2

        wait_for_condition(
            two_zip_files_present,
            seconds_max=121,
            seconds_interval=5,
            progress_string_fn=zip_file_list,
        )
        # expected_instances = dict(Series=)
        assert zip_files
        for z in zip_files:
            unzip_dir = tmp_path_factory.mktemp("unzip_dir", numbered=True)
            self._check_dcm_tags_from_zip(z, unzip_dir)

    def _check_dcm_tags_from_zip(self, zip_path, unzip_dir) -> None:
        """Check that private tag has survived anonymisation with the correct value."""
        run_subprocess(
            ["unzip", zip_path],
            working_dir=unzip_dir,
        )
        all_dicom = list(unzip_dir.rglob("*.dcm"))

        # I think this will fail if we've done it right?
        # assert len(all_dicom) == 1

        # within a dicom study, there can be multiple dicom instances, but none should
        # have a series description on the exclude list
        logging.info("JES: within zip, all_dicom [%s] = %s", len(all_dicom), all_dicom)
        for dcm_file in all_dicom:
            dcm = pydicom.dcmread(dcm_file)
            logging.info("JES: dcm_file = %s", dcm_file)
            logging.info(
                "JES: AN = %s, PI = %s, SD = %s",
                dcm.get("AccessionNumber"),
                dcm.get("PatientID"),
                dcm.get("SeriesDescription"),
            )
            block = dcm.private_block(
                DICOM_TAG_PROJECT_NAME.group_id, DICOM_TAG_PROJECT_NAME.creator_string
            )
            tag_offset = DICOM_TAG_PROJECT_NAME.offset_id
            private_tag = block[tag_offset]
            assert private_tag is not None
            assert private_tag.value == TestFtpsUpload.project_slug


@pytest.mark.usefixtures("_setup_pixl_cli")
def test_ehr_anon_entries():
    """Check data has reached ehr_anon."""

    def exists_two_rows() -> bool:
        # This was converted from old shell script - better to check more than just row count?
        sql_command = "select * from emap_data.ehr_anon"
        cp = run_subprocess(
            [
                "docker",
                "exec",
                "system-test-postgres-1",
                "/bin/bash",
                "-c",
                f'PGPASSWORD=pixl_db_password psql -U pixl_db_username -d pixl -c "{sql_command}"',
            ],
            Path.cwd(),
        )
        return cp.stdout.decode().find("(2 rows)") != -1

    # We already waited in _setup_pixl_cli, so should be true immediately.
    wait_for_condition(exists_two_rows)
