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
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from asyncio import sleep
from json import JSONDecodeError
from time import time
from typing import Any, Optional

import requests
from decouple import config
from requests.auth import HTTPBasicAuth

logger = logging.getLogger("uvicorn")


class Orthanc(ABC):
    def __init__(self, url: str, username: str, password: str) -> None:
        self._url = url.rstrip("/")
        self._username = username
        self._password = password

        self._auth = HTTPBasicAuth(username=username, password=password)

    @property
    @abstractmethod
    def aet(self) -> str:
        """Application entity title (AET) of this Orthanc instance"""

    @property
    def modalities(self) -> Any:
        """Accessible modalities from this Orthanc instance"""
        return self._get("/modalities")

    def query_local(self, data: dict) -> list[str] | list[dict]:
        """Query local Orthanc instance for resourceId."""
        return self._post("/tools/find", data=data)

    def query_remote(self, data: dict, modality: str) -> Optional[str]:
        """Query a particular modality, available from this node"""
        logger.debug("Running query on modality: %s with %s", modality, data)

        response = self._post(
            f"/modalities/{modality}/query",
            data=data,
            timeout=config("PIXL_QUERY_TIMEOUT", default=10, cast=float),
        )
        logger.debug("Query response: %s", response)

        if len(self._get(f"/queries/{response['ID']}/answers")) > 0:
            return str(response["ID"])

        return None

    def modify_private_tags_by_study(
        self,
        *,
        study_id,
        private_creator,
        tag_replacement: dict,
    ) -> Any:
        # According to the docs, you can't modify tags for an instance using the instance API
        # (the best you can do is download a modified version), so do it via the studies API.
        # KeepSource=false needed to stop it making a copy
        # https://orthanc.uclouvain.be/api/index.html#tag/Studies/paths/~1studies~1{id}~1modify/post
        return self._post(
            f"/studies/{study_id}/modify",
            {
                "PrivateCreator": private_creator,
                "Permissive": False,
                "KeepSource": False,
                "Replace": tag_replacement,
            },
        )

    def retrieve_from_remote(self, query_id: str) -> str:
        response = self._post(
            f"/queries/{query_id}/retrieve",
            data={"TargetAet": self.aet, "Synchronous": False},
        )
        return str(response["ID"])

    async def wait_for_job_success(self, query_id, timeout) -> None:
        job_id = self.retrieve_from_remote(query_id=query_id)  # C-Move
        job_state = "Pending"
        start_time = time()

        while job_state != "Success":
            if (time() - start_time) > timeout:
                raise TimeoutError

            await sleep(0.1)
            job_state = self.job_state(job_id=job_id)

    def job_state(self, job_id: str) -> str:
        # See: https://book.orthanc-server.com/users/advanced-rest.html#jobs-monitoring
        return str(self._get(f"/jobs/{job_id}")["State"])

    def _get(self, path: str) -> Any:
        return _deserialise(requests.get(f"{self._url}{path}", auth=self._auth, timeout=10))

    def _post(
        self, path: str, data: dict, timeout: Optional[float] = None
    ) -> list[str] | list[dict]:
        return _deserialise(
            requests.post(f"{self._url}{path}", json=data, auth=self._auth, timeout=timeout)
        )

    def _delete(self, path: str, timeout: Optional[float] = 10) -> None:
        return _deserialise(requests.delete(f"{self._url}{path}", auth=self._auth, timeout=timeout))

    def send_existing_study_to_anon(self, resource_id: str) -> None:
        """Send study to orthanc anon."""
        self._post("/send-to-anon", data={"ResourceId": resource_id})


def _deserialise(response: requests.Response) -> Any:
    """Decode an Orthanc rest API response"""
    success_code = 200
    if response.status_code != success_code:
        msg = (
            f"Failed request. "
            f"Status code: {response.status_code}"
            f"Content: {response.content.decode()}"
        )
        raise requests.HTTPError(msg)
    try:
        return response.json()
    except (JSONDecodeError, ValueError) as exc:
        msg = f"Failed to parse {response} as json"
        raise requests.HTTPError(msg) from exc


class PIXLRawOrthanc(Orthanc):
    def __init__(self) -> None:
        super().__init__(
            url=config("ORTHANC_RAW_URL"),
            username=config("ORTHANC_RAW_USERNAME"),
            password=config("ORTHANC_RAW_PASSWORD"),
        )

    @property
    def aet(self) -> str:
        return str(config("ORTHANC_RAW_AE_TITLE"))
