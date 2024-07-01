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

from pixl_dcmd._dicom_helpers import DicomValidator
from pixl_dcmd.main import anonymise_dicom
from pydicom import Dataset


def test_validation_check_works(vanilla_dicom_image: Dataset) -> None:
    """
    GIVEN a DICOM dataset
    WHEN the dataset is validated against itself (withouth anonymisation)
    THEN no errors should be raised
    """
    validator = DicomValidator()
    validator.validate_original(vanilla_dicom_image)
    assert not validator.validate_anonymised(vanilla_dicom_image)


def test_validation_after_anonymisation_works(
    row_for_dicom_testing, vanilla_dicom_image: Dataset
) -> None:
    """
    GIVEN a DICOM dataset
    WHEN the dataset is validated after anonymisation
    THEN no errors should be raised
    """
    validator = DicomValidator()
    validator.validate_original(vanilla_dicom_image)
    anonymise_dicom(vanilla_dicom_image)
    assert not validator.validate_anonymised(vanilla_dicom_image)


def test_validation_fails_after_invalid_tag_modification(vanilla_dicom_image) -> None:
    """
    GIVEN a DICOM dataset
    WHEN an invalid tag operation is performed (e.g. deleting a required tag)
    THEN validation should return a non-empty list of errors
    """
    validator = DicomValidator()
    validator.validate_original(vanilla_dicom_image)
    del vanilla_dicom_image.PatientName
    validation_result = validator.validate_anonymised(vanilla_dicom_image)

    assert len(validation_result) == 1
    assert "Patient" in validation_result.keys()
    assert len(validation_result["Patient"]) == 1
    assert (
        "Tag (0010,0010) (Patient's Name) is missing"
        in validation_result["Patient"].keys()
    )
