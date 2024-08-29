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
import re
from pathlib import Path

import nibabel
import numpy as np
import pydicom
import pytest
import sqlalchemy
from core.db.models import Image
from core.dicom_tags import (
    DICOM_TAG_PROJECT_NAME,
    PrivateDicomTag,
    add_private_tag,
    create_private_tag,
)
from core.project_config import load_project_config, load_tag_operations
from decouple import config

from pixl_dcmd._dicom_helpers import get_study_info
from pixl_dcmd.main import (
    _anonymise_dicom_from_scheme,
    anonymise_and_validate_dicom,
    anonymise_dicom,
    _enforce_allowlist,
    _should_exclude_series,
)
from pytest_pixl.dicom import generate_dicom_dataset
from pytest_pixl.helpers import run_subprocess

PROJECT_CONFIGS_DIR = Path(config("PROJECT_CONFIGS_DIR"))
TEST_PROJECT_SLUG = "test-extract-uclh-omop-cdm"


@pytest.fixture(scope="module")
def tag_scheme() -> list[dict]:
    """Base tag scheme for testing."""
    tag_ops = load_tag_operations(load_project_config(TEST_PROJECT_SLUG))
    return tag_ops.base[0]


def _mri_diffusion_tags(manufacturer: str = "Philips") -> list[PrivateDicomTag]:
    """
    Private DICOM tags for testing the anonymisation process.
    These tags from `/projects/configs/tag-operations/manufacturer-overrides/mri-diffusion.yaml`
    so we can test whether the manufacturer overrides work during anonymisation
    """
    project_config = load_project_config(TEST_PROJECT_SLUG)
    tag_ops = load_tag_operations(project_config)
    mri_diffusion_overrides = tag_ops.manufacturer_overrides[0]

    manufacturer_overrides = [
        override
        for override in mri_diffusion_overrides
        if re.search(override["manufacturer"], manufacturer, re.IGNORECASE)
    ][0]

    return [
        create_private_tag(tag["group"], tag["element"], vr="SH", value="test")
        for tag in manufacturer_overrides["tags"]
    ]


@pytest.fixture()
def mri_diffusion_dicom_image() -> pydicom.Dataset:
    """
    A DICOM image with diffusion data to test the anonymisation process.
    Private tags were added to match the tag operations defined in the project config, so we can
    test whether the anonymisation process works as expected when defining overrides.
    """
    manufacturer = "Philips"
    ds = generate_dicom_dataset(Manufacturer=manufacturer, Modality="DX")
    tags = _mri_diffusion_tags(manufacturer)
    for tag in tags:
        add_private_tag(ds, tag)

    # Make sure the project name tag is added for anonymisation to work
    add_private_tag(ds, DICOM_TAG_PROJECT_NAME)
    # Update the project name tag to a known value
    block = ds.private_block(
        DICOM_TAG_PROJECT_NAME.group_id, DICOM_TAG_PROJECT_NAME.creator_string
    )
    ds[block.get_tag(DICOM_TAG_PROJECT_NAME.offset_id)].value = TEST_PROJECT_SLUG

    return ds


def test_enforce_allowlist_removes_overlay_plane() -> None:
    """Checks that overlay planes are removed."""
    ds = pydicom.data.get_testdata_file(
        "MR-SIEMENS-DICOM-WithOverlays.dcm", read=True, download=True
    )
    assert (0x6000, 0x3000) in ds

    _enforce_allowlist(ds, {}, recursive=True)
    assert (0x6000, 0x3000) not in ds


def test_anonymisation(vanilla_dicom_image: pydicom.Dataset) -> None:
    """
    Test whether anonymisation works as expected on a vanilla DICOM dataset
    """

    orig_patient_id = vanilla_dicom_image.PatientID
    orig_patient_name = vanilla_dicom_image.PatientName

    # Sanity check: study date should be present before anonymisation
    assert "StudyDate" in vanilla_dicom_image

    anonymise_dicom(vanilla_dicom_image)

    assert vanilla_dicom_image.PatientID != orig_patient_id
    assert vanilla_dicom_image.PatientName != orig_patient_name
    assert "StudyDate" not in vanilla_dicom_image


def test_anonymise_unimplemented_tag(vanilla_dicom_image: pydicom.Dataset) -> None:
    """
    GIVEN DICOM data with an OB data type tag within a sequence
    WHEN anonymise_dicom is run that has "replace" tag operation on the sequence, but not the OB element
    THEN the sequence should exist, but not the OB element

    VR OB is not implemented by the dicom anonymisation library, so this
    is testing that we can still successfully de-identify data with this data type
    """
    nested_ds = pydicom.Dataset()
    nested_block = nested_ds.private_block(0x0013, "VR OB CREATOR", create=True)
    nested_block.add_new(0x0011, "OB", b"")

    # create private sequence tag with the nested dataset
    block = vanilla_dicom_image.private_block(0x0013, "VR OB CREATOR", create=True)
    block.add_new(0x0010, "SQ", [nested_ds])

    anonymise_dicom(vanilla_dicom_image)

    assert (0x0013, 0x0010) in vanilla_dicom_image
    assert (0x0013, 0x1010) in vanilla_dicom_image
    sequence = vanilla_dicom_image[(0x0013, 0x1010)]
    assert (0x0013, 0x1011) not in sequence[0]


def test_anonymise_and_validate_as_external_user() -> None:
    """
    GIVEN an example MR dataset and configuration to anonymise this
    WHEN the anonymisation and validation is called not using PIXL infrastructure
    THEN the dataset is anonymised inplace

    Note: If we update this test, make sure to update the documentation stub.
    Or if we end up building docs, then convert this test to a doctest
    """
    dataset_path = pydicom.data.get_testdata_file(
        "MR-SIEMENS-DICOM-WithOverlays.dcm", download=True
    )
    config_path = (
        pathlib.Path(__file__).parents[2] / "projects/configs/test-external-user.yaml"
    )
    dataset = pydicom.dcmread(dataset_path)
    validation_issues = anonymise_and_validate_dicom(
        dataset, config_path=config_path, synchronise_pixl_db=False
    )

    assert validation_issues == {}
    assert dataset != pydicom.dcmread(dataset_path)


# TODO: test that anonymise_and_validate_dicom() works as expected
# https://github.com/SAFEHR-data/PIXL/issues/418


def test_anonymisation_with_overrides(
    mri_diffusion_dicom_image: pydicom.Dataset, row_for_mri_dicom_testing
) -> None:
    """
    Test that the anonymisation process works with manufacturer overrides.
    GIVEN a dicom image with manufacturer-specific private tags
    WHEN the anonymisation is applied
    THEN all tag operations should be applied, obeying any manufacturer overrides
    """

    # Sanity check
    # (0x2001, 0x1003) is one of the tags allow-listed by the overrides for Philips manufacturer
    assert (0x2001, 0x1003) in mri_diffusion_dicom_image
    original_patient_id = mri_diffusion_dicom_image.PatientID
    original_private_tag = mri_diffusion_dicom_image[(0x2001, 0x1003)]

    anonymise_dicom(mri_diffusion_dicom_image)

    # Whitelisted tags should still be present
    assert (0x0010, 0x0020) in mri_diffusion_dicom_image
    assert (0x2001, 0x1003) in mri_diffusion_dicom_image
    assert mri_diffusion_dicom_image.PatientID != original_patient_id
    assert mri_diffusion_dicom_image[(0x2001, 0x1003)] == original_private_tag


def test_image_already_exported_throws(rows_in_session, exported_dicom_dataset):
    """
    GIVEN a dicom image which has no un-exported rows in the pipeline database
    WHEN the dicom tag scheme is applied
    THEN an exception will be thrown as
    """
    # Make sure the project name tag is added for anonymisation to work
    add_private_tag(exported_dicom_dataset, DICOM_TAG_PROJECT_NAME)
    # Update the project name tag to a known value
    block = exported_dicom_dataset.private_block(
        DICOM_TAG_PROJECT_NAME.group_id, DICOM_TAG_PROJECT_NAME.creator_string
    )
    exported_dicom_dataset[
        block.get_tag(DICOM_TAG_PROJECT_NAME.offset_id)
    ].value = TEST_PROJECT_SLUG
    with pytest.raises(sqlalchemy.exc.NoResultFound):
        anonymise_dicom(exported_dicom_dataset)


def test_pseudo_identifier_processing(
    rows_in_session, monkeypatch, exported_dicom_dataset, not_exported_dicom_dataset
):
    """
    GIVEN a dicom image that hasn't been exported in the pipeline db
    WHEN the dicom tag scheme is applied
    THEN the patient identifier tag should be the mrn hashed
        the study instance uid should be replaced with a new uid
        and the db should have the pseudo study id
    """
    exported_study_info = get_study_info(exported_dicom_dataset)
    not_exported_study_info = get_study_info(not_exported_dicom_dataset)

    class FakeUID:
        i = 1

        @classmethod
        def fake_uid(cls):
            uid = f"2.25.{cls.i}"
            cls.i += 1
            return pydicom.uid.UID(uid)

    monkeypatch.setattr("pixl_dcmd._database.generate_uid", FakeUID.fake_uid)
    other_image = (
        rows_in_session.query(Image)
        .filter(Image.accession_number == exported_study_info.accession_number)
        .one()
    )
    other_image.pseudo_study_uid = "2.25.1"
    rows_in_session.add(other_image)
    rows_in_session.commit()

    mrn = exported_study_info.mrn
    fake_hash = "-".join(list(mrn))
    print("fake_hash = ", fake_hash)
    anonymise_dicom(not_exported_dicom_dataset)
    image = (
        rows_in_session.query(Image)
        .filter(Image.accession_number == not_exported_study_info.accession_number)
        .one()
    )
    print("after tags applied")
    assert not_exported_dicom_dataset[0x0010, 0x0020].value == fake_hash
    assert image.pseudo_study_uid == not_exported_dicom_dataset[0x0020, 0x000D].value
    assert image.pseudo_study_uid == "2.25.2"  # 2nd image in the db


def test_pseudo_patient_id_processing(
    row_for_testing_image_with_pseudo_patient_id, not_exported_dicom_dataset
):
    """
    GIVEN an `Image` entity in the database which has a `pseudo_patient_id` set
    WHEN the matching DICOM data is anonymised
    THEN the DICOM's patient ID tag should be the original `pseudo_study_id`
    value from the database, the database's `pseudo_patient_id` shouldn't have changed
    """
    study_info = get_study_info(not_exported_dicom_dataset)
    original_image: Image = (
        row_for_testing_image_with_pseudo_patient_id.query(Image)
        .filter(Image.accession_number == study_info.accession_number)
        .one()
    )
    assert (
        not_exported_dicom_dataset[0x0010, 0x0020].value
        != original_image.pseudo_patient_id
    )

    anonymise_dicom(not_exported_dicom_dataset)

    anonymised_image: Image = (
        row_for_testing_image_with_pseudo_patient_id.query(Image)
        .filter(Image.accession_number == study_info.accession_number)
        .one()
    )

    assert original_image.pseudo_patient_id == anonymised_image.pseudo_patient_id
    assert (
        not_exported_dicom_dataset[0x0010, 0x0020].value
        == original_image.pseudo_patient_id
    )


def test_no_pseudo_patient_id_processing(rows_in_session, not_exported_dicom_dataset):
    """
    GIVEN an `Image` entity in the database which doesn't have a `pseudo_patient_id` set
    WHEN the matching DICOM data is anonymised
    THEN database's `pseudo_patient_id` field should be set, and match the value from the
    DICOM's patient identifier tag at the end of anonymisation
    """
    study_info = get_study_info(not_exported_dicom_dataset)

    anonymise_dicom(not_exported_dicom_dataset)

    anonymised_image: Image = (
        rows_in_session.query(Image)
        .filter(Image.accession_number == study_info.accession_number)
        .one()
    )

    assert anonymised_image.pseudo_patient_id is not None
    assert (
        anonymised_image.pseudo_patient_id
        == not_exported_dicom_dataset[0x0010, 0x0020].value
    )


@pytest.fixture()
def dicom_series_to_keep() -> list[pydicom.Dataset]:
    series = [
        "",
        "whatever",
    ]
    return [_make_dicom(s) for s in series]


@pytest.fixture()
def dicom_series_to_exclude() -> list[pydicom.Dataset]:
    series = [
        "positioning",
        "foo_barpositioning",
        "positioningla",
        "scout",
        "localiser",
        "localizer",
        # Matching should be case insensitive
        "lOcALIsER",
    ]
    return [_make_dicom(s) for s in series]


def _make_dicom(series_description) -> pydicom.Dataset:
    ds = generate_dicom_dataset(SeriesDescription=series_description)
    add_private_tag(ds, DICOM_TAG_PROJECT_NAME, "test-extract-uclh-omop-cdm")
    return ds


def test_should_exclude_series(dicom_series_to_exclude, dicom_series_to_keep):
    config = load_project_config(TEST_PROJECT_SLUG)
    for s in dicom_series_to_keep:
        assert not _should_exclude_series(s, config)
    for s in dicom_series_to_exclude:
        assert _should_exclude_series(s, config)


def test_can_nifti_convert_post_anonymisation(
    row_for_mri_dicom_testing, tmp_path, directory_of_mri_dicoms, tag_scheme
):
    """Can a DICOM image that has passed through our tag processing be converted to NIFTI"""
    # Create a directory to store anonymised DICOM files
    anon_dicom_dir = tmp_path / "anon"
    anon_dicom_dir.mkdir()
    tag_scheme += [
        {
            "group": 0x0020,
            "element": 0x0032,
            "name": "Image Position (Patient)",
            "op": "keep",
        },
        {
            "group": 0x0020,
            "element": 0x0037,
            "name": "Image Orientation (Patient)",
            "op": "keep",
        },
        {
            "group": 0x0018,
            "element": 0x0023,
            "name": "MR Acquisition Type",
            "op": "keep",
        },
    ]
    # Get test DICOMs from the fixture, anonymise and save
    for dcm_path in directory_of_mri_dicoms.glob("*.dcm"):
        dcm = pydicom.dcmread(dcm_path)
        _anonymise_dicom_from_scheme(dcm, TEST_PROJECT_SLUG, tag_scheme)
        pydicom.dcmwrite(anon_dicom_dir / dcm_path.name, dcm)

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


@pytest.fixture
def sequenced_dicom_mock_db(monkeypatch):
    """
    Create a DICOM dataset with
    a private sequence tag
        (group=0x0011, offset=0x0010, creator="UCLH PIXL", VR="SQ"),
        a private child tag
            (group=0x0011, offset=0x0011, creator="UCLH PIXL", VR="SH", value="nested_priv_tag) and
        a public child tag
            (group=0x0010, element=0x0020), VR="LO", value="987654321").

    Also mock db functions
    """
    # Create a test DICOM with a sequence tag
    exported_dicom = pathlib.Path(__file__).parents[2] / "test/resources/Dicom1.dcm"
    dataset = pydicom.dcmread(exported_dicom)
    # create nested dataset to put into sequence
    nested_ds = pydicom.Dataset()
    # nested public tag
    nested_ds.add_new((0x0010, 0x0020), "LO", "987654321")
    # nested private tag
    nested_block = nested_ds.private_block(0x0011, "UCLH PIXL", create=True)
    nested_block.add_new(0x0011, "SH", "nested_priv_tag")

    # create private sequence tag with the nested dataset
    block = dataset.private_block(0x0011, "UCLH PIXL", create=True)
    block.add_new(0x0010, "SQ", [nested_ds])

    # Mock the database functions
    monkeypatch.setattr(
        "pixl_dcmd.main.get_uniq_pseudo_study_uid_and_update_db", lambda *args: None
    )
    return dataset


def test_del_tag_keep_sq(sequenced_dicom_mock_db):
    """
    GIVEN a dicom image that has a private sequence tag marked to be kept with
    - a private child tag that is marked to be deleted
    - a public child tag that is marked to be replaced
    WHEN the dicom anonymisation is applied
    THEN
    - the sequence tag should be kept
    - the child tags should be deleted/replaced
    """
    ## ARRANGE (or rather check arrangement is as expected)
    assert (0x0011, 0x0010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1011) in sequenced_dicom_mock_db.get_private_item(
        0x0011, 0x0010, "UCLH PIXL"
    )[0]
    assert (
        sequenced_dicom_mock_db.get_private_item(0x0011, 0x0010, "UCLH PIXL")[0]
        .get_private_item(0x0011, 0x0011, "UCLH PIXL")
        .value
        == "nested_priv_tag"
    )
    assert (0x0010, 0x0020) in sequenced_dicom_mock_db.get_private_item(
        0x0011, 0x0010, "UCLH PIXL"
    )[0]
    assert (
        sequenced_dicom_mock_db.get_private_item(0x0011, 0x0010, "UCLH PIXL")[0]
        .get_item((0x0010, 0x0020))
        .value
        == "987654321"
    )

    # Create a tag scheme that deletes the nested tags, but keeps the parent
    tag_scheme = [
        {
            "group": 0x0011,
            "element": 0x0010,  # creator
            "op": "keep",
        },
        {
            "group": 0x0011,
            "element": 0x1010,  # sequence
            "op": "keep",
        },
        {
            "group": 0x0011,
            "element": 0x1011,  # private child
            "op": "delete",
        },
        {
            "group": 0x0010,
            "element": 0x0020,  # public child
            "op": "replace",
        },
    ]

    ## ACT
    _anonymise_dicom_from_scheme(sequenced_dicom_mock_db, TEST_PROJECT_SLUG, tag_scheme)

    ## ASSERT
    # Check that the sequence tag has been kept
    assert (0x0011, 0x0010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1010) in sequenced_dicom_mock_db
    # check private tag is deleted
    assert (0x0011, 0x1011) not in sequenced_dicom_mock_db.get_private_item(
        0x0011, 0x0010, "UCLH PIXL"
    )[0]
    # check public tag is replaced
    assert (
        sequenced_dicom_mock_db.get_private_item(0x0011, 0x0010, "UCLH PIXL")[0]
        .get_item((0x0010, 0x0020))
        .value
        != "987654321"
    )


def test_keep_tag_del_sq(sequenced_dicom_mock_db):
    """
    GIVEN a dicom image that has a private sequence tag marked to be deleted with
        a private child tag that is marked to be kept
    WHEN the dicom anonymisation is applied
    THEN the sequence tag should be deleted
    """
    ## ARRANGE (or rather check arrangement is as expected)
    assert (0x0011, 0x0010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1010) in sequenced_dicom_mock_db

    # Create a tag scheme that deletes the sequence tag, but keeps the nested tags
    tag_scheme = [
        {
            "group": 0x0011,
            "element": 0x1010,
            "op": "delete",
        },
        {
            "group": 0x0011,
            "element": 0x1011,
            "op": "keep",
        },
        {
            "group": 0x0010,
            "element": 0x0020,
            "op": "replace",
        },
    ]
    ## ACT
    _anonymise_dicom_from_scheme(sequenced_dicom_mock_db, TEST_PROJECT_SLUG, tag_scheme)

    ## ASSERT
    # Check that the sequence tag has been deleted
    assert (0x0011, 0x1010) not in sequenced_dicom_mock_db
    with pytest.raises(KeyError):
        sequenced_dicom_mock_db.get_private_item(0x0011, 0x0010, "UCLH PIXL")


def test_allowlist_child_elements_deleted(sequenced_dicom_mock_db):
    """
    GIVEN a dicom image that has a public and private sequence tags
    WHEN the dicom tag scheme is applied
    THEN the sequence tags should be deleted
    """
    ## ARRANGE (or rather check arrangement is as expected)
    # check that the sequence tag is present
    assert (0x0011, 0x0010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1010) in sequenced_dicom_mock_db
    # check that the children are present
    assert (0x0011, 0x1011) in sequenced_dicom_mock_db[(0x0011, 0x1010)][0]
    sequenced_dicom_mock_db[(0x0011, 0x1010)][0][
        (0x0011, 0x1011)
    ].value == "nested_priv_tag"
    assert (0x0010, 0x0020) in sequenced_dicom_mock_db[(0x0011, 0x1010)][0]
    sequenced_dicom_mock_db[(0x0011, 0x1010)][0][(0x0010, 0x0020)].value == "987654321"

    # set tag scheme to keep sequence
    tag_scheme = [
        {
            "group": 0x0011,
            "element": 0x0010,
            "op": "keep",
        },
        {
            "group": 0x0011,
            "element": 0x1010,
            "op": "keep",
        },
    ]
    # Whitelist
    _enforce_allowlist(sequenced_dicom_mock_db, tag_scheme, recursive=True)

    # Check that the sequence tag is kept
    assert (0x0011, 0x0010) in sequenced_dicom_mock_db
    assert (0x0011, 0x1010) in sequenced_dicom_mock_db
    # Check that children are deleted
    assert (0x0011, 0x1011) not in sequenced_dicom_mock_db[(0x0011, 0x1010)][0]
    assert (0x0010, 0x0020) not in sequenced_dicom_mock_db[(0x0011, 0x1010)][0]
    with pytest.raises(KeyError):
        sequenced_dicom_mock_db[(0x0011, 0x1010)][0].get_private_item(
            0x0011, 0x0011, "UCLH PIXL"
        )
    with pytest.raises(KeyError):
        sequenced_dicom_mock_db[(0x0011, 0x1010)][0][0x0010, 0x0020]
