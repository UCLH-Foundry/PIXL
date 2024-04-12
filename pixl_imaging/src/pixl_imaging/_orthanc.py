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

from abc import ABC, abstractmethod
from asyncio import sleep
from time import time
from typing import Any, Optional

import aiohttp
from core.exceptions import PixlRequeueMessageError, PixlSkipMessageError
from decouple import config
from loguru import logger


class Orthanc(ABC):
    def __init__(self, url: str, username: str, password: str) -> None:
        if not url:
            msg = "URL for orthanc is required"
            raise ValueError(msg)
        self._url = url.rstrip("/")
        self._username = username
        self._password = password

        self._auth = aiohttp.BasicAuth(login=username, password=password)

    @property
    @abstractmethod
    def aet(self) -> str:
        """Application entity title (AET) of this Orthanc instance"""

    @property
    async def modalities(self) -> Any:
        """Accessible modalities from this Orthanc instance"""
        return await self._get("/modalities")

    async def get_jobs(self) -> Any:
        """Get expanded details for all jobs."""
        return await self._get("/jobs?expand")

    async def query_local(self, data: dict) -> Any:
        """Query local Orthanc instance for resourceId."""
        return await self._post("/tools/find", data=data)

    async def query_remote(self, data: dict, modality: str) -> Optional[str]:
        """Query a particular modality, available from this node"""
        logger.debug("Running query on modality: {} with {}", modality, data)

        response = await self._post(
            f"/modalities/{modality}/query",
            data=data,
            timeout=config("PIXL_QUERY_TIMEOUT", default=10, cast=float),
        )
        logger.debug("Query response: {}", response)
        query_answers = await self._get(f"/queries/{response['ID']}/answers")
        if len(query_answers) > 0:
            return str(response["ID"])

        return None

    async def modify_private_tags_by_study(
        self,
        *,
        study_id: str,
        private_creator: str,
        tag_replacement: dict,
    ) -> Any:
        # According to the docs, you can't modify tags for an instance using the instance API
        # (the best you can do is download a modified version), so do it via the studies API.
        # KeepSource=false needed to stop it making a copy
        # https://orthanc.uclouvain.be/api/index.html#tag/Studies/paths/~1studies~1{id}~1modify/post
        return await self._post(
            f"/studies/{study_id}/modify",
            {
                "PrivateCreator": private_creator,
                "Permissive": False,
                "KeepSource": False,
                "Replace": tag_replacement,
            },
        )

    async def retrieve_from_remote(self, query_id: str) -> str:
        response = await self._post(
            f"/queries/{query_id}/retrieve",
            data={"TargetAet": self.aet, "Synchronous": False},
        )
        return str(response["ID"])

    async def wait_for_job_success_or_raise(self, query_id: str, timeout: float) -> None:
        """Wait for job to complete successfully, or raise exception if fails or exceeds timeout."""
        job_id = await self.retrieve_from_remote(query_id=query_id)  # C-Move
        job_state = "Pending"
        start_time = time()

        while job_state != "Success":
            if job_state == "Failure":
                msg = f"Job failed for {job_id}"
                raise PixlSkipMessageError(msg)

            if (time() - start_time) > timeout:
                msg = f"Failed to transfer {job_id} in {timeout} seconds"
                raise PixlSkipMessageError(msg)

            await sleep(1)
            job_state = await self.job_state(job_id=job_id)

    async def job_state(self, job_id: str) -> str:
        """Get job state from orthanc."""
        # See: https://book.orthanc-server.com/users/advanced-rest.html#jobs-monitoring
        job = await self._get(f"/jobs/{job_id}")
        return str(job["State"])

    async def _get(self, path: str) -> Any:
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{self._url}{path}", auth=self._auth, timeout=10) as response,
        ):
            return await _deserialise(response)

    async def _post(self, path: str, data: dict, timeout: Optional[float] = None) -> Any:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{self._url}{path}", json=data, auth=self._auth, timeout=timeout
            ) as response,
        ):
            return await _deserialise(response)

    async def delete(self, path: str, timeout: Optional[float] = 10) -> None:
        async with (
            aiohttp.ClientSession() as session,
            session.delete(f"{self._url}{path}", auth=self._auth, timeout=timeout) as response,
        ):
            await _deserialise(response)


async def _deserialise(response: aiohttp.ClientResponse) -> Any:
    """Decode an Orthanc rest API response"""
    response.raise_for_status()
    return await response.json()


class PIXLRawOrthanc(Orthanc):
    """Orthanc Raw connection."""

    def __init__(self) -> None:
        super().__init__(
            url=config("ORTHANC_RAW_URL"),
            username=config("ORTHANC_RAW_USERNAME"),
            password=config("ORTHANC_RAW_PASSWORD"),
        )

    async def raise_if_pending_jobs(self) -> None:
        """
        Raise PixlRequeueMessageError if there are pending jobs on the server.

        Otherwise orthanc starts to get buggy when there are a whole load of pending jobs.
        PixlRequeueMessageError will cause the rabbitmq message to be requeued
        """
        jobs = await self.get_jobs()
        for job in jobs:
            if job["State"] == "Pending":
                msg = "Pending messages in orthanc raw"
                raise PixlRequeueMessageError(msg)

    @property
    def aet(self) -> str:
        return str(config("ORTHANC_RAW_AE_TITLE"))

    async def send_existing_study_to_anon(self, resource_id: str) -> Any:
        """Send study to orthanc anon."""
        return await self._post("/send-to-anon", data={"ResourceId": resource_id})
