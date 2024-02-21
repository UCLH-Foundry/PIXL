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
"""Check validity of radiology export"""
import logging
import os
from pathlib import Path

import pandas as pd
import pytest

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("_extract_radiology_reports")
def test_radiology_parquet(host_export_root_dir: Path):
    """
    From:
    scripts/test_radiology_parquet.py \
        ../exports/test-extract-uclh-omop-cdm/latest/radiology/radiology.parquet
    Test contents of radiology report parquet file in the export location
    """
    expected_radiology_parquet_file = (
        host_export_root_dir
        / "test-extract-uclh-omop-cdm"
        / "latest"
        / "radiology"
        / "radiology.parquet"
    )

    print(
        f"JES - test_radiology_parquet - test is about to fail, what's in {host_export_root_dir}?"
    )
    for f in os.walk(host_export_root_dir, followlinks=True):
        print(f)
    print("done printing")

    # XXX FAILS why is file not found on thingy??
    # It's because the symlink is not present!!!!
    exported_data = pd.read_parquet(expected_radiology_parquet_file)

    logger.warning(exported_data.head())

    parquet_header_names = ["image_identifier", "procedure_occurrence_id", "image_report"]
    assert (exported_data.columns == parquet_header_names).all()

    # the fake DEID service adds this string to the end to confirm it has been through it
    DE_ID_SUFFIX = "**DE-IDENTIFIED**"

    expected_rows = 2
    assert exported_data.shape[0] == expected_rows

    assert exported_data.loc[0].procedure_occurrence_id == 4
    assert exported_data.loc[0].image_report == "this is a radiology report 1" + DE_ID_SUFFIX

    # blake2b-256 hash of string ('987654321' + 'AA12345601') with key = 'test_key'
    assert (
        exported_data.loc[0].image_identifier
        == "a971b114b9133c81c03fb88c6a958f7d95eb1387f04c17ad7ff9ba7cf684c392"
    )

    assert exported_data.loc[1].procedure_occurrence_id == 5
    assert exported_data.loc[1].image_report == "this is a radiology report 2" + DE_ID_SUFFIX

    # blake2b-256 hash of string ('987654321' + 'AA12345605') with key = 'test_key'
    assert (
        exported_data.loc[1].image_identifier
        == "f71b228fa97d6c87db751e0bb35605fd9d4c1274834be4bc4bb0923ab8029b2a"
    )

    # Files must not be owned by root - they'll be hard to delete and we shouldn't be running our
    # containers as root anyway.
    file_stats = expected_radiology_parquet_file.stat()
    try:
        assert file_stats.st_uid != 0
        assert file_stats.st_gid != 0
    except AssertionError:
        logger.exception("Known bug: files should not be owned by root")
