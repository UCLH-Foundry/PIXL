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
"""
Uploader package
Contains base uploader class and
- FTPS uploader class
- **in progress** Azure uploader class
- **in progress** DICOMWeb uploader class

Uploader class gets appropriate secret credentials from Azure key vault and uploads data
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.uploader._dicomweb import DicomWebUploader
from core.uploader._ftps import FTPSUploader

if TYPE_CHECKING:
    from core.uploader.base import Uploader


# Intenitonally defined in __init__.py to avoid circular imports
def get_uploader(project_slug: str, destination: str, keyvault_alias: Optional[str]) -> Uploader:
    """Uploader Factory, returns uploader instance based on destination."""
    choices: dict[str, type[Uploader]] = {"ftps": FTPSUploader, "dicomweb": DicomWebUploader}
    try:
        return choices[destination](project_slug, keyvault_alias)

    except KeyError:
        error_msg = f"Destination '{destination}' is currently not supported"
        raise NotImplementedError(error_msg) from None
