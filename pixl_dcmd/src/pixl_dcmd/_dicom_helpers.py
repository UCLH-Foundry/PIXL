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
"""Helper functions for DICOM data."""

from __future__ import annotations

import logging
from pathlib import Path

from core.dicom_tags import DICOM_TAG_PROJECT_NAME
from dicom_validator.spec_reader.edition_reader import EditionReader
from dicom_validator.validator.iod_validator import IODValidator
from loguru import logger
from pydicom import Dataset


def get_project_name_as_string(dataset: Dataset) -> str:
    raw_slug = dataset.get_private_item(
        DICOM_TAG_PROJECT_NAME.group_id,
        DICOM_TAG_PROJECT_NAME.offset_id,
        DICOM_TAG_PROJECT_NAME.creator_string,
    ).value
    # Get both strings and bytes, which is fun
    if isinstance(raw_slug, bytes):
        logger.debug(f"Bytes slug {raw_slug!r}")
        slug = raw_slug.decode("utf-8").strip()
    else:
        logger.debug(f"String slug '{raw_slug}'")
        slug = raw_slug
    return slug


class DicomValidator:
    def __init__(self, edition: str = "current"):
        self.edition = edition

        # Default from dicom_validator but defining here to be explicit
        standard_path = str(Path.home() / "dicom-validator")
        edition_reader = EditionReader(standard_path)
        destination = edition_reader.get_revision(self.edition, False)
        json_path = Path(destination, "json")
        self.dicom_info = EditionReader.load_dicom_info(json_path)

    def validate_original(self, dataset: Dataset) -> None:
        # Temporarily disable logging to avoid spamming the console
        logging.disable(logging.ERROR)
        self.original_errors = IODValidator(dataset, self.dicom_info).validate()
        logging.disable(logging.NOTSET)

    def validate_anonymised(self, dataset: Dataset) -> dict:
        # Check that the original dataset has been validated
        try:
            orig_errors = self.original_errors
        except AttributeError:
            raise ValueError("Original dataset not yet validated")

        # Temporarily disable logging to avoid spamming the console
        logging.disable(logging.ERROR)
        self.anon_errors = IODValidator(dataset, self.dicom_info).validate()
        logging.disable(logging.NOTSET)

        self.diff_errors: dict = {}

        for key in self.anon_errors.keys():
            if key in self.original_errors.keys():
                # Keep only errors introduced after the anonymisation
                # The keys of the dictionary containt the actual errors
                diff = set(self.anon_errors[key].keys()) - set(orig_errors[key].keys())
                if diff:
                    self.diff_errors[key] = diff
            else:
                self.diff_errors[key] = self.anon_errors[key]

        return self.diff_errors
