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
            seconds_condition_stays_true_for=15,
            progress_string_fn=zip_file_list,
        )
        expected_studies = {
            "a971b114b9133c81c03fb88c6a958f7d95eb1387f04c17ad7ff9ba7cf684c392": [
                # hash of AA12345601
                {"AccessionNumber": "ad630a8a84d72d71", "SeriesDescription": "whatever1"},
                {"AccessionNumber": "ad630a8a84d72d71", "SeriesDescription": "AP"},
            ],
            "f71b228fa97d6c87db751e0bb35605fd9d4c1274834be4bc4bb0923ab8029b2a": [
                # hash of AA12345605,
                {"AccessionNumber": "c2f4b59b0291c6fe", "SeriesDescription": "whatever1"},
            ],
        }
        assert zip_files
        for z in zip_files:
            unzip_dir = tmp_path_factory.mktemp("unzip_dir", numbered=True)
            self._check_dcm_tags_from_zip(z, unzip_dir, expected_studies)

    def _check_dcm_tags_from_zip(self, zip_path, unzip_dir, expected_studies) -> None:
        """Check that private tag has survived anonymisation with the correct value."""
        expected_instances = expected_studies[zip_path.stem]
        run_subprocess(
            ["unzip", zip_path],
            working_dir=unzip_dir,
        )
        dicom_in_zip = list(unzip_dir.rglob("*.dcm"))

        # One zip file == one study.
        # There can be multiple instances in the zip file, one per file
        logging.info("JES: within zip, dicom_in_zip [%s] = %s", len(dicom_in_zip), dicom_in_zip)
        for dcm_file in dicom_in_zip:
            dcm = pydicom.dcmread(dcm_file)
            # The actual dicom filename and dir structure isn't checked - should it be?
            logging.info("JES: dcm_file = %s", dcm_file)
            assert dcm.get("PatientID") == zip_path.stem  # PatientID stores study id post anon
            actual_info = {
                "AccessionNumber": dcm.get("AccessionNumber"),
                "SeriesDescription": dcm.get("SeriesDescription"),
            }
            logging.info("Actual info = %s", actual_info)
            assert actual_info in expected_instances
            block = dcm.private_block(
                DICOM_TAG_PROJECT_NAME.group_id, DICOM_TAG_PROJECT_NAME.creator_string
            )
            tag_offset = DICOM_TAG_PROJECT_NAME.offset_id
            private_tag = block[tag_offset]
            assert private_tag is not None
            if isinstance(private_tag.value, bytes):
                # Allow this for the time being, until it has been investigated
                # See https://github.com/UCLH-Foundry/PIXL/issues/363
                logging.error(
                    "TEMPORARILY IGNORE: tag value %s should be of type str, but is of type bytes",
                    {private_tag.value},
                )
                assert private_tag.value.decode() == TestFtpsUpload.project_slug
            else:
                assert private_tag.value == TestFtpsUpload.project_slug
        # nothing got left out
        assert len(dicom_in_zip) == len(expected_instances)


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
