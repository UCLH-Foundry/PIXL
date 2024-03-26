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

import pathlib

import nibabel
import numpy as np
import pydicom
import pytest
import sqlalchemy
import yaml
from core.db.models import Image
from pixl_dcmd.main import (
    anonymise_dicom,
    apply_tag_scheme,
    merge_tag_schemes,
    remove_overlays,
)
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from pytest_pixl.helpers import run_subprocess


@pytest.fixture(scope="module")
def tag_scheme() -> dict:
    """Read the tag scheme from orthanc raw."""
    tag_file = (
        pathlib.Path(__file__).parents[2]
        / "projects/configs/tag-operations/test-extract-uclh-omop-cdm.yaml"
    )
    return yaml.safe_load(tag_file.read_text())


def test_remove_overlay_plane() -> None:
    """Checks that overlay planes are removed."""
    ds = get_testdata_file(
        "MR-SIEMENS-DICOM-WithOverlays.dcm", read=True, download=True
    )
    assert (0x6000, 0x3000) in ds

    ds_minus_overlays = remove_overlays(ds)
    assert (0x6000, 0x3000) not in ds_minus_overlays


# TODO: Produce more complete test coverage for anonymisation
# https://github.com/UCLH-Foundry/PIXL/issues/132


def test_anonymisation(rows_in_session, mri_diffusion_dicom_image: Dataset) -> None:
    """
    Test that the anonymisation process works.
    GIVEN a dicom image
    WHEN the anonymisation is applied
    THEN all tag operations should be applied
    """

    # Sanity check
    assert (0x2001, 0x1003) in mri_diffusion_dicom_image

    anon_ds = anonymise_dicom(mri_diffusion_dicom_image)

    # Whitelisted tags should still be present
    assert (0x2001, 0x1003) in anon_ds


def test_image_already_exported_throws(rows_in_session, tag_scheme):
    """
    GIVEN a dicom image which has no un-exported rows in the pipeline database
    WHEN the dicom tag scheme is applied
    THEN an exception will be thrown as
    """
    exported_dicom = pathlib.Path(__file__).parents[2] / "test/resources/Dicom1.dcm"
    input_dataset = pydicom.dcmread(exported_dicom)

    with pytest.raises(sqlalchemy.exc.NoResultFound):
        apply_tag_scheme(input_dataset, tag_scheme)


def test_pseudo_identifier_processing(rows_in_session, tag_scheme):
    """
    GIVEN a dicom image that hasn't been exported in the pipeline db
    WHEN the dicom tag scheme is applied
    THEN the patient identifier tag should be the mrn and accession hashed
      and the pipeline db row should now have the fake hash
    """
    exported_dicom = pathlib.Path(__file__).parents[2] / "test/resources/Dicom2.dcm"
    input_dataset = pydicom.dcmread(exported_dicom)

    accession_number = "AA12345605"
    mrn = "987654321"
    fake_hash = "-".join(list(f"{mrn}{accession_number}"))
    print("fake_hash = ", fake_hash)
    output_dataset = apply_tag_scheme(input_dataset, tag_scheme)
    image = (
        rows_in_session.query(Image)
        .filter(Image.accession_number == "AA12345605")
        .one()
    )
    print("after tags applied")
    assert output_dataset[0x0010, 0x0020].value == fake_hash
    assert image.hashed_identifier == fake_hash


def test_can_nifti_convert_post_anonymisation(
    row_for_dicom_testing, tmp_path, directory_of_mri_dicoms, tag_scheme
):
    """Can a DICOM image that has passed through our tag processing be converted to NIFTI"""
    # Create a directory to store anonymised DICOM files
    anon_dicom_dir = tmp_path / "anon"
    anon_dicom_dir.mkdir()

    # Get test DICOMs from the fixture, anonymise and save
    for dcm_path in directory_of_mri_dicoms.glob("*.dcm"):
        dcm_identifiable = pydicom.dcmread(dcm_path)
        dcm_anon = apply_tag_scheme(dcm_identifiable, tag_scheme)
        pydicom.dcmwrite(anon_dicom_dir / dcm_path.name, dcm_anon)

    # Convert the anonymised DICOMs to NIFTI with dcm2niix
    anon_nifti_dir = tmp_path / "nifti_anon"
    anon_nifti_dir.mkdir()
    run_subprocess(
        ["dcm2niix", "-f", "anon", "-o", str(anon_nifti_dir), str(anon_dicom_dir)],
    )

    # Convert the pre-anonymisation DICOMs to NIFTI with dcm2niix
    ident_nifti_dir = tmp_path / "nifti_ident"
    ident_nifti_dir.mkdir()
    run_subprocess(
        [
            "dcm2niix",
            "-f",
            "ident",
            "-o",
            str(ident_nifti_dir),
            str(directory_of_mri_dicoms),
        ],
    )

    # Confirm that the shape, orientation and contents of the pre- and
    # post- anonymisation images match
    anon_nifti = nibabel.load(anon_nifti_dir / "anon.nii")
    ident_nifti = nibabel.load(ident_nifti_dir / "ident.nii")
    assert anon_nifti.shape == ident_nifti.shape
    assert np.all(anon_nifti.header.get_sform() == ident_nifti.header.get_sform())
    assert np.all(anon_nifti.get_fdata() == ident_nifti.get_fdata())


def test_merge_tag_schemes_single_file():
    tag_ops_file = (
        pathlib.Path(__file__).parents[2]
        / "projects/configs/tag-operations/test-extract-uclh-omop-cdm.yaml"
    )
    merge_tag_schemes([tag_ops_file])


def test_merge_multiple_tag_schemes():
    base_tag_ops_file = (
        pathlib.Path(__file__).parents[2]
        / "projects/configs/tag-operations/test-extract-uclh-omop-cdm.yaml"
    )
    # Merging the same file twice should be the same as merging it once
    expected = merge_tag_schemes([base_tag_ops_file])
    result = merge_tag_schemes([base_tag_ops_file, base_tag_ops_file])
    assert result == expected
