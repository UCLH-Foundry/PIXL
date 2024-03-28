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

"""Utilities for the system test"""

import json
import shlex
import subprocess

from pytest_pixl.helpers import wait_for_condition


def wait_for_stable_orthanc_anon(
    seconds_max, seconds_interval, seconds_condition_stays_true_for
) -> None:
    """
    Query the orthanc-anon REST API to check that the correct number of instances
    have been received.
    If they haven't within the time limit, raise a TimeoutError
    """
    instances = []

    def are_three_instances() -> bool:
        nonlocal instances
        instances_cmd = shlex.split(
            "docker exec system-test-orthanc-anon-1 "
            'curl -u "orthanc_anon_username:orthanc_anon_password" '
            "http://orthanc-anon:8042/instances"
        )
        instances_output = subprocess.run(instances_cmd, capture_output=True, check=True, text=True)  # noqa: S603
        instances = json.loads(instances_output.stdout)
        return len(instances) == 3

    def list_instances() -> str:
        return f"orthanc-anon instances: {instances}"

    wait_for_condition(
        are_three_instances,
        seconds_max=seconds_max,
        seconds_interval=seconds_interval,
        progress_string_fn=list_instances,
        seconds_condition_stays_true_for=seconds_condition_stays_true_for,
    )
