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
"""Collection of functions for deidentifaction of text"""

from __future__ import annotations

import os

import requests
from requests.auth import HTTPBasicAuth

COGSTACK_URL = os.environ["COGSTACK_REDACT_URL"]
COGSTACK_USER = os.environ["COGSTACK_REDACT_USER"]
COGSTACK_PASSWORD = os.environ["COGSTACK_REDACT_PASSWORD"]


def deidentify_text(text: str) -> str:
    """Query the cogstack redact API to deidentify input text."""
    response = requests.post(
        COGSTACK_URL,
        data={"text": text, "modelid": "6"},
        headers={"Content-Type": "text/plain"},
        timeout=10,
        auth=HTTPBasicAuth(COGSTACK_USER, COGSTACK_PASSWORD),
    )
    success_code = 200

    if response.status_code != success_code:
        msg = (
            f"Failed request. "
            f"Status code: {response.status_code}"
            f"Content: {response.content.decode()}"
        )
        raise requests.HTTPError(msg)

    return response.text
