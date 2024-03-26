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
"""
For defining private DICOM tags.
This information is currently duplicated in
 - pixl_imaging/tests/orthanc_raw_config/orthanc.json
 - orthanc/orthanc-raw/config/orthanc.json
 - projects/configs/tag-operations/test-extract-uclh-omop-cdm.yaml

For now you will have to manually keep these in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pydicom.dataset import Dataset


@dataclass
class PrivateDicomTag:
    """
    Define private DICOM tags that we are using in PIXL.
    We don't specify the private block ID (eg. 0x10) because its value can vary to avoid collisions
    - the private creator string is used to locate the block.
    Unfortunately, Orthanc seems to require you to hardcode it if you want to be able to use
    the API to update the tag value. So we have to take what we're given and log an error if
    it's not 0x10.
    """

    group_id: int
    offset_id: int
    required_private_block: int
    creator_string: str
    tag_nickname: str
    # LO = Long string max 64
    # https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_6.2.html
    vr: str
    unknown_value: Optional[str] = "__pixl_unknown_value__"

    def acceptable_private_block(self, actual_private_block: int) -> bool:
        """
        Detect whether the private block given to us is acceptable
        :param actual_private_block: one byte private block ID
        """
        if not 0x10 <= actual_private_block <= 0xFF:  # noqa: PLR2004 see DICOM spec
            err_str = f"private block must be from 0x10 to 0xff, got {actual_private_block}"
            raise ValueError(err_str)
        if self.required_private_block is None:
            return True
        return self.required_private_block == actual_private_block


DICOM_TAG_PROJECT_NAME = PrivateDicomTag(
    group_id=0x000D,
    required_private_block=0x10,
    offset_id=0x01,
    creator_string="UCLH PIXL",
    tag_nickname="UCLHPIXLProjectName",
    vr="LO",
    unknown_value="__pixl_unknown_value__",
)


def add_private_tag(dataset: Dataset, private_tag: PrivateDicomTag) -> None:
    """
    Add a private tag to an existing DICOM dataset.

    This uses pydicom.Dataset.private_block

    :param ds: The DICOM dataset to add the private tags to.
    :type ds: pydicom.Dataset
    :param private_tag: A custom tag to add to the DICOM dataset.
    """
    private_block = dataset.private_block(
        private_tag.group_id, private_tag.creator_string, create=True
    )
    private_block.add_new(private_tag.offset_id, private_tag.vr, private_tag.unknown_value)


def create_private_tag(group_id: int, element_id: int, vr: str, value: Any) -> PrivateDicomTag:
    """
    Creates a valid private DICOM tag from a group and element id, by calculating the required
    offset.
    """
    return PrivateDicomTag(
        group_id=group_id,
        # The offset is the element id minus the private block start, which seems to be always
        # equal to 0x1000 (4096)
        offset_id=element_id - 0x1000,
        required_private_block=0x10,
        creator_string="UCLH PIXL",
        tag_nickname="UCLHPIXLProjectName",
        vr=vr,
        unknown_value=value,
    )
