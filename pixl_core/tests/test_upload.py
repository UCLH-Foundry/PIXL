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


import pytest
from core.upload import upload_content


@pytest.mark.usefixtures("_run_containers")
def test_upload_content(data, mounted_data, ftp_remote_dir) -> None:
    """Tests that file is present on the endpoint after upload"""
    local_file = data / "public.zip"
    with local_file.open("rb") as handle:
        output_file = upload_content(handle, remote_file="public.zip", remote_dir=ftp_remote_dir)

    assert (mounted_data / output_file).exists()
