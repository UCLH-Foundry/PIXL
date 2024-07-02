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

"""Uploader subclass for DICOMweb uploads."""

from __future__ import annotations

import json
from typing import Optional

import requests
from decouple import config  # type: ignore [import-untyped]
from loguru import logger

from core.uploader.base import Uploader


class DicomWebUploader(Uploader):
    """Upload strategy for a DicomWeb server."""

    def __init__(self, project_slug: str, keyvault_alias: Optional[str]) -> None:
        """Create instance of parent class"""
        super().__init__(project_slug, keyvault_alias)

    def _set_config(self) -> None:
        # Use the Azure KV alias as prefix if it exists, otherwise use the project name
        az_prefix = self.keyvault_alias
        self.az_prefix = az_prefix if az_prefix else self.project_slug

        self.orthanc_user = config("ORTHANC_ANON_USERNAME")
        self.orthanc_password = config("ORTHANC_ANON_PASSWORD")
        self.orthanc_url = config("ORTHANC_ANON_URL")
        self.endpoint_user = self.keyvault.fetch_secret(f"{self.az_prefix}--dicomweb--username")
        self.endpoint_password = self.keyvault.fetch_secret(f"{self.az_prefix}--dicomweb--password")
        self.endpoint_url = self.keyvault.fetch_secret(f"{self.az_prefix}--dicomweb--url")
        # The DICOMweb API endpoint on the Orthanc server, used by Orthanc to interact with the
        # DICOMweb server. Note that this is different from the endpoint_url, which is the URL of
        # the DICOMweb server itself.
        self.orthanc_dicomweb_url = self.orthanc_url + "/dicom-web/servers/" + self.az_prefix
        self.http_timeout = int(config("HTTP_TIMEOUT", default=30))

    def _upload_dicom_image(
        self, study_id: str, pseudo_anon_image_id: str, project_slug: str
    ) -> None:
        """Upload a Dicom resource to the DicomWeb server from within Orthanc."""
        logger.info("Starting DICOMweb upload of '{}' for {}", pseudo_anon_image_id, project_slug)
        if not self._check_dicomweb_server_exists():
            logger.info("Creating new DICOMWeb credentials")
            self._setup_dicomweb_credentials()

        self._validate_dicomweb_server()

        headers = {"content-type": "application/json", "accept": "application/dicom+json"}
        payload = {"Resources": [study_id], "Synchronous": True}

        try:
            response = requests.post(
                self.orthanc_dicomweb_url + "/stow",
                auth=(self.orthanc_user, self.orthanc_password),
                headers=headers,
                data=json.dumps(payload),
                timeout=self.http_timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            logger.error("Failed to send via stow")
            raise
        logger.info("Finished DICOMweb upload of '{}'", pseudo_anon_image_id)

    def _check_dicomweb_server_exists(self) -> bool:
        """Checks if the dicomweb server exists."""
        response = requests.get(
            self.orthanc_dicomweb_url,
            auth=(self.orthanc_user, self.orthanc_password),
            timeout=self.http_timeout,
        )
        success_code = 200
        if response.status_code != success_code:
            return False
        return True

    def _validate_dicomweb_server(self) -> None:
        """Check if the DICOMweb server is reachable from within the Orthanc instance."""
        connection_error = requests.exceptions.ConnectionError("DICOMweb server not reachable")
        if not self._check_dicomweb_server_exists():
            logger.error("DICOMweb server not configured")
            raise connection_error

        # If dicomweb server configured, check if we can reach it
        try:
            response = requests.post(
                self.orthanc_dicomweb_url + "/get",
                auth=(self.orthanc_user, self.orthanc_password),
                data='{"Uri": "/studies"}',
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=self.http_timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error("Failed to reach DICOMweb server")
            raise connection_error from e

    def _setup_dicomweb_credentials(self) -> None:
        """
        Add the necessary credentials to the DicomWeb server in Orthanc.
        This dynamically creates a new endpoint in Orthanc with the necessary credentials, so we
        can avoid hardcoding the credentials in the Orthanc configuration at build time.
        """
        dicomweb_config = {
            "Url": self.endpoint_url,
            "Username": self.endpoint_user,
            "Password": self.endpoint_password,
            "HasDelete": True,
            "Timeout": self.http_timeout,
        }

        headers = {"content-type": "application/json"}
        try:
            response = requests.put(
                self.orthanc_dicomweb_url,
                auth=(self.orthanc_user, self.orthanc_password),
                headers=headers,
                data=json.dumps(dicomweb_config),
                timeout=10,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            logger.error("Failed to update DICOMweb config for {}", self.orthanc_dicomweb_url)
            raise
        else:
            logger.info("Set up DICOMweb config for {}", self.orthanc_dicomweb_url)

        self._validate_dicomweb_server()

    def upload_parquet_files(self) -> None:
        msg = "DICOMWeb uploader does not support parquet files"
        raise NotImplementedError(msg)
