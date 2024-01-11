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

import pydicom
import yaml
from pydicom.data import get_testdata_files

from pixl_dcmd.main import (
    apply_tag_scheme,
    remove_overlays,
)


def test_remove_overlay_plane() -> None:
    """Checks that overlay planes are removed."""
    fpath = get_testdata_files("MR-SIEMENS-DICOM-WithOverlays.dcm")[0]
    ds = pydicom.dcmread(fpath)
    assert (0x6000, 0x3000) in ds

    ds_minus_overlays = remove_overlays(ds)
    assert (0x6000, 0x3000) not in ds_minus_overlays


# TODO: Produce more complete test coverage for anonymisation
# https://github.com/UCLH-Foundry/PIXL/issues/132
def test_no_unexported_image_throws(rows_in_session):
    """
    GIVEN a dicom image which has already been exported
    WHEN the dicom tag scheme is applied
    THEN an exception will be thrown as
    """
    exported_dicom = pathlib.Path(__file__).parents[4] / "test/resources/Dicom1.dcm"
    input_dataset = pydicom.dcmread(exported_dicom)

    tag_file = (
        pathlib.Path(__file__).parents[4]
        / "orthanc/orthanc-anon/plugin/tag-operations.yaml"
    )
    tags_scheme = yaml.safe_load(tag_file.read_text())
    apply_tag_scheme(input_dataset, tags_scheme)
