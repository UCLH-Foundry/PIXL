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
"""Test functionality to upload files to an endpoint."""

import filecmp
import pathlib
from datetime import datetime, timezone

import pandas as pd
import pytest
from core.db.models import Image
from core.db.queries import update_exported_at
from core.exports import ParquetExport
from sqlalchemy.exc import NoResultFound


@pytest.mark.usefixtures("ftps_server")
def test_upload_dicom_image(
    test_zip_content, not_yet_exported_dicom_image, ftps_uploader, ftps_home_dir
) -> None:
    """Tests that DICOM image can be uploaded to the correct location"""
    # ARRANGE
    # Get the pseudo identifier from the test image
    pseudo_anon_id = not_yet_exported_dicom_image.hashed_identifier
    project_slug = "some-project-slug"
    expected_output_file = ftps_home_dir / project_slug / (pseudo_anon_id + ".zip")

    # ACT
    ftps_uploader.upload_dicom_image(test_zip_content, pseudo_anon_id, project_slug)

    # ASSERT
    assert expected_output_file.exists()


@pytest.mark.usefixtures("ftps_server")
def test_upload_dicom_image_already_exported(
    test_zip_content, already_exported_dicom_image, ftps_uploader
) -> None:
    """Tests that exception thrown if DICOM image already exported"""
    # ARRANGE
    # Get the pseudo identifier from the test image
    pseudo_anon_id = already_exported_dicom_image.hashed_identifier
    project_slug = "some-project-slug"

    # ASSERT
    with pytest.raises(RuntimeError, match="Image already exported"):
        ftps_uploader.upload_dicom_image(test_zip_content, pseudo_anon_id, project_slug)


@pytest.mark.usefixtures("ftps_server")
def test_upload_dicom_image_unknown(test_zip_content, ftps_uploader) -> None:
    """
    Tests that a different exception is thrown if image is not recognised in the PIXL DB.

    This supports the correctness of test_upload_dicom_image_already_exported,
    which tests if the image is known, but has already been uploaded before uploading.
    """
    # ARRANGE
    pseudo_anon_id = "doesnotexist"
    project_slug = "some-project-slug"

    # ASSERT
    with pytest.raises(NoResultFound):
        ftps_uploader.upload_dicom_image(test_zip_content, pseudo_anon_id, project_slug)


def test_update_exported_and_save(rows_in_session) -> None:
    """Tests that the exported_at field is updated when a file is uploaded"""
    # ARRANGE
    expected_export_time = datetime.now(tz=timezone.utc)

    # ACT
    update_exported_at("not_yet_exported", expected_export_time)
    new_row = (
        rows_in_session.query(Image).filter(Image.hashed_identifier == "not_yet_exported").one()
    )
    actual_export_time = new_row.exported_at.replace(tzinfo=timezone.utc)

    # ASSERT
    assert actual_export_time == expected_export_time


@pytest.fixture()
def parquet_export(export_dir) -> ParquetExport:
    """
    Return a ParquetExport object.

    This fixture is deliberately not definied in conftest, because it imports the ParquetExport
    class, which in turn loads the PixlConfig class, which in turn requres the PROJECT_CONFIGS_DIR
    environment to be set. This environment variable is set in conftest, so the import needs to
    happen after that.
    """
    return ParquetExport(
        project_name="i-am-a-project",
        extract_datetime=datetime.now(tz=timezone.utc),
        export_dir=export_dir,
    )


@pytest.mark.usefixtures("ftps_server")
def test_upload_parquet(parquet_export, ftps_home_dir, ftps_uploader) -> None:
    """Tests that parquet files are uploaded to the correct location"""
    # ARRANGE

    parquet_export.copy_to_exports(
        pathlib.Path(__file__).parents[3] / "test" / "resources" / "omop"
    )
    parquet_export.export_radiology(pd.DataFrame(list("dummy"), columns=["D"]))

    # ACT
    ftps_uploader.upload_parquet_files(parquet_export)

    # ASSERT
    expected_public_parquet_dir = (
        ftps_home_dir / parquet_export.project_slug / parquet_export.extract_time_slug / "parquet"
    )
    assert expected_public_parquet_dir.exists()

    # Print difference report to aid debugging (it doesn't actually assert anything)
    dc = filecmp.dircmp(parquet_export.current_extract_base, expected_public_parquet_dir)
    dc.report_full_closure()
    assert (
        expected_public_parquet_dir / "omop" / "public" / "PROCEDURE_OCCURRENCE.parquet"
    ).exists()
    assert (expected_public_parquet_dir / "radiology" / "radiology.parquet").exists()


@pytest.mark.usefixtures("ftps_server")
def test_no_export_to_upload(parquet_export, ftps_uploader) -> None:
    """If there is nothing in the export directly, an exception is thrown"""
    parquet_export.public_output.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        ftps_uploader.upload_parquet_files(parquet_export)
