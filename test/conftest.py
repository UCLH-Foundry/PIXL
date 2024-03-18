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
"""System/E2E test setup"""
import os
import subprocess
from pathlib import Path

import pytest
from pytest_pixl.helpers import run_subprocess
from pytest_pixl.plugin import FtpHostAddress
from utils import wait_for_stable_orthanc_anon

pytest_plugins = "pytest_pixl"


@pytest.fixture(scope="session")
def host_export_root_dir():
    """Intermediate export dir as seen from the host"""
    return Path(__file__).parents[1] / "projects" / "exports"


TEST_DIR = Path(__file__).parent
RESOURCES_DIR = TEST_DIR / "resources"
RESOURCES_OMOP_DIR = RESOURCES_DIR / "omop"

PIXL_USER_UID = os.getenv("PIXL_USER_UID")
PIXL_USER_GID = os.getenv("PIXL_USER_GID")


@pytest.fixture(scope="session")
def _setup_pixl_cli(ftps_server, host_export_root_dir) -> None:
    """Run pixl populate/start. Cleanup intermediate export dir on exit."""
    # see if it's already created
    try:
        print("JES: trying first ls -laR")
        run_subprocess(["ls", "-laR", host_export_root_dir.parents[0]])
    except subprocess.CalledProcessError:
        try:
            print("JES: trying second ls -laR")
            run_subprocess(["ls", "-laR", host_export_root_dir.parents[1]])
        except subprocess.CalledProcessError:
            pass

    # In production, it will be documented that the exports directory must be writable
    # by the "pixl" user. For the system test we must do it here.
    if os.getenv("GITHUB_ACTIONS") == "true":
        run_subprocess(
            [
                "sudo",
                "--non-interactive",
                "groupadd",
                "--gid",
                str(PIXL_USER_GID),
                "pixl",
            ]
        )
        run_subprocess(
            [
                "sudo",
                "--non-interactive",
                "useradd",
                "--uid",
                str(PIXL_USER_UID),
                "--gid",
                str(PIXL_USER_GID),
                "pixl",
            ]
        )
        # this directory is part of the git repo so will already exist
        run_subprocess(
            ["sudo", "--non-interactive", "chown", "-R", "pixl:pixl", host_export_root_dir]
        )
    print("JES: after create user pixl")
    run_subprocess(["cat", "/etc/passwd"])

    print("JES: afterwards ls -laR")
    run_subprocess(["ls", "-laR", host_export_root_dir.parents[0]])
    # CLI calls need to have CWD = test dir so they can find the pixl_config.yml file
    run_subprocess(["pixl", "populate", str(RESOURCES_OMOP_DIR.absolute())], TEST_DIR)
    # poll here for two minutes to check for imaging to be processed, printing progress
    wait_for_stable_orthanc_anon(121, 5)
    yield
    run_subprocess(
        [
            "docker",
            "exec",
            "system-test-ehr-api-1",
            "rm",
            "-r",
            "/run/projects/exports/test-extract-uclh-omop-cdm/",
        ],
        TEST_DIR,
    )


@pytest.fixture(scope="session")
def ftp_host_address():
    """Run FTP on docker host - docker containers do need to access it"""
    return FtpHostAddress.DOCKERHOST


@pytest.fixture(scope="session")
def _extract_radiology_reports(_setup_pixl_cli) -> None:
    """
    run pixl extract-radiology-reports. No subsequent wait is needed, because this API call
    is synchronous (whether that is itself wise is another matter).
    """
    run_subprocess(
        ["pixl", "extract-radiology-reports", str(RESOURCES_OMOP_DIR.absolute())], TEST_DIR
    )
