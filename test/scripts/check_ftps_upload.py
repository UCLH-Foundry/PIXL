#!/usr/bin/env python
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
from pathlib import Path

PARQUET_PATH = Path(__file__).parents[1] / "resources" / "omop"
print(f"parquet path: {PARQUET_PATH}")
MOUNTED_DATA_DIR = Path(__file__).parents[1] / "dummy-services" / "ftp-server" / "mounts" / "data"
print(f"mounted data dir: {MOUNTED_DATA_DIR}")

project_name = "test-extract-uclh-omop-cdm"
print(f"project name: {project_name}")
expected_output_dir = MOUNTED_DATA_DIR / project_name
print(f"expected output dir: {expected_output_dir}")

# Test whether DICOM images have been uploaded
glob_list = list(expected_output_dir.glob("*.zip"))
print(f"glob_list: {glob_list}")

assert len(glob_list) == 1

# TODO: check parquet files upload