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
"""Check requirements related to docker configuration."""

import pytest
from loguru import logger
from pytest_pixl.helpers import run_subprocess


@pytest.mark.usefixtures("_setup_pixl_cli")
@pytest.mark.parametrize(
    "container",
    [
        "export-api",
        "imaging-api",
        "hasher-api",
        "postgres",
        "queue",
        "orthanc-raw",
        "orthanc-anon",
        "vna-qr",
        "dicomweb-server",
    ],
)
def test_non_root_uids(container: str) -> None:
    """
    Test that all processes inside certain containers are not running as root.
    This is easier for ones we have full control over, but
    we may wish to expand the list of containers as we fix them.
    It would also be good to check that they're running as a particular user, but
    non-root will do for now.
    """
    cp = run_subprocess(["docker", "top", f"system-test-{container}-1"])
    lines = cp.stdout.decode().splitlines()
    logger.info(lines)
    assert lines[0].startswith("UID")  # sanity check title line
    for proc in lines[1:]:
        uid = proc.split(" ")[0]
        assert uid != "root"
