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
import logging

from pixl_dcmd.main import apply_tag_scheme, remove_overlays, write_dataset_to_bytes

from ._version import __version__, __version_info__

__all__ = ["remove_overlays", "write_dataset_to_bytes", "apply_tag_scheme"]

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
