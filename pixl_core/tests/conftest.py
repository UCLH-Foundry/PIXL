#  Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
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

import os
import subprocess
from pathlib import Path

import pytest

os.environ["RABBITMQ_USERNAME"] = "guest"
os.environ["RABBITMQ_PASSWORD"] = "guest"  # noqa: S105 Harcoding password
os.environ["RABBITMQ_HOST"] = "localhost"
os.environ["RABBITMQ_PORT"] = "25672"
os.environ["FTP_HOST"] = "localhost"
os.environ["FTP_USER_NAME"] = "pixl"
os.environ["FTP_USER_PASS"] = "pixl"  # noqa: S105 Harcoding password
os.environ["FTP_PORT"] = "20021"

TEST_DIR = Path(__file__).parent


@pytest.fixture(scope="session")
def _run_containers() -> None:
    """WIP, should  be able to get this up and running from pytest"""
    subprocess.run(
        "docker compose --build --wait up".split(" "),
        check=True,
        cwd=TEST_DIR,
        shell=True,  # noqa: S602
    )
    yield
    subprocess.run("docker compose down --volumes".split(" "), check=True, cwd=TEST_DIR, shell=True)  # noqa: S602
