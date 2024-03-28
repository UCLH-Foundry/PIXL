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

from dataclasses import dataclass
from typing import Any

from pydicom import Dataset
from pydicom.dataset import PrivateBlock


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

    PLACEHOLDER_VALUE = "__pixl_unknown_value__"

    group_id: int
    offset_id: int
    # (aka VR) https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_6.2.html
    value_type: str
    required_private_block: int
    creator_string: str
    tag_nickname: str

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

    def add_to_dicom_dataset(self, dataset: Dataset, value: Any) -> PrivateBlock:
        """Add this private tag to the given dicom dataset, setting the given value"""
        private_block = dataset.private_block(self.group_id, self.creator_string, create=True)
        private_block.add_new(self.offset_id, self.value_type, value)
        if not self.acceptable_private_block(private_block.block_start >> 8):
            err_str = (
                "The private block does not match the value hardcoded in the orthanc "
                "config. This can be because there was an unexpected pre-existing private block "
                f"in group {self.group_id}"
            )
            raise RuntimeError(err_str)
        return private_block


DICOM_TAG_PROJECT_NAME = PrivateDicomTag(
    group_id=0x000D,
    required_private_block=0x10,
    offset_id=0x01,
    value_type="LO",  # LO = Long string max 64
    creator_string="UCLH PIXL",
    tag_nickname="UCLHPIXLProjectName",
)
