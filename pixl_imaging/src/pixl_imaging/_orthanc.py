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
from core.exceptions import PixlDiscardError, PixlRequeueMessageError
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
        query_answers = await self.get_remote_query_answers(response["ID"])
        if len(query_answers) > 0:
            return str(response["ID"])

        return None

    async def get_remote_query_answers(self, query_id: str) -> Any:
        """Get the answers to a query"""
        return await self._get(f"/queries/{query_id}/answers")

    async def get_remote_query_answer_content(self, query_id: str, answer_id: str) -> Any:
        """Get the content of a query answer"""
        return await self._get(f"/queries/{query_id}/answers/{answer_id}/content")

    async def modify_private_tags_by_study(
        self,
        *,
        study_id: str,
        private_creator: str,
        tag_replacement: dict,
        timeout: float,
    ) -> None:
        # According to the docs, you can't modify tags for an instance using the instance API
        # (the best you can do is download a modified version), so do it via the studies API.
        # KeepSource=false needed to stop it making a copy
        # https://orthanc.uclouvain.be/api/index.html#tag/Studies/paths/~1studies~1{id}~1modify/post
        response = await self._post(
            f"/studies/{study_id}/modify",
            {
                "PrivateCreator": private_creator,
                "Permissive": False,
                "KeepSource": False,
                "Replace": tag_replacement,
                "Asynchronous": True,
            },
        )
        logger.debug("Modify studies Job: {}", response)
        job_id = str(response["ID"])
        try:
            await self.wait_for_job_success_or_raise(job_id, "modify", timeout=timeout)
        except PixlDiscardError:
            logger.warning(f"Deleting study {study_id} as modify job failed")
            await self.delete(f"/studies/{study_id}")
            raise

    async def retrieve_from_remote(self, query_id: str) -> str:
        response = await self._post(
            f"/queries/{query_id}/retrieve",
            data={"TargetAet": self.aet, "Synchronous": False},
        )
        return str(response["ID"])

    async def wait_for_job_success_or_raise(
        self, job_id: str, job_type: str, timeout: float
    ) -> None:
        """Wait for job to complete successfully, or raise exception if fails or exceeds timeout."""
        job_info = {"State": "Pending"}
        start_time = time()

        while job_info["State"] != "Success":
            if job_info["State"] == "Failure":
                msg = (
                    "Job failed: "
                    f"Error code={job_info['ErrorCode']} Cause={job_info['ErrorDescription']}"
                )
                raise PixlDiscardError(msg)
            if job_type == "modify":
                logger.debug("Modify job: {}", job_info)
            if (time() - start_time) > timeout:
                msg = f"Failed to finish {job_type} job {job_id} in {timeout} seconds"
                await sleep(10)
                raise PixlDiscardError(msg)

            await sleep(10)
            job_info = await self.job_state(job_id=job_id)

    async def job_state(self, job_id: str) -> Any:
        """Get job state from orthanc."""
        # See: https://book.orthanc-server.com/users/advanced-rest.html#jobs-monitoring
        return await self._get(f"/jobs/{job_id}")

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
        unfinished_jobs = [x for x in jobs if x["State"] not in ("Success", "Failure")]
        for job in unfinished_jobs:
            logger.trace(
                "{}, {}, {}, {}, {}",
                job["State"],
                job.get("CreationTime"),
                job.get("ID"),
                job.get("Type"),
                job.get("EffectiveRuntime"),
            )
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
