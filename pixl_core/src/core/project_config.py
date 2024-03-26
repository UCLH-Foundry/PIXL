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

"""Project-specific configuration for Pixl."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from decouple import Config, RepositoryEmpty, RepositoryEnv
from pydantic import BaseModel, field_validator

# Make sure local .env file is loaded if it exists
env_file = Path.cwd() / ".env"
config = Config(RepositoryEnv(env_file)) if env_file.exists() else Config(RepositoryEmpty())

logger = logging.getLogger(__name__)


def load_project_config(project_slug: str) -> PixlConfig | Any:
    """
    Load configuration for a project based on its slug.
    Project needs to have a corresponding yaml file in the `$PROJECT_CONFIGS_DIR` directory.
    """
    configpath = Path(config("PROJECT_CONFIGS_DIR")) / f"{project_slug}.yaml"
    logger.warning(f"Loading config for {project_slug} from {configpath}")  # noqa: G004
    if not configpath.exists():
        raise FileNotFoundError(f"No config for {project_slug}. Please submit PR and redeploy.")  # noqa: EM102, TRY003
    return _load_and_validate(configpath)


def _load_and_validate(filename: Path) -> PixlConfig | Any:
    """
    Load configuration from a yaml file.
    :param filename: Path to the yaml file
    """
    yaml_data = yaml.safe_load(filename.read_text())
    return PixlConfig.model_validate(yaml_data)


class _Project(BaseModel):
    name: str
    azure_kv_alias: Optional[str] = None
    modalities: list[str]


class _DestinationEnum(str, Enum):
    """Defines the valid upload destinations."""

    none = "none"
    ftps = "ftps"


class _Destination(BaseModel):
    dicom: _DestinationEnum
    parquet: _DestinationEnum

    @field_validator("parquet")
    @classmethod
    def valid_parquet_destination(cls, v: str) -> str:
        if v == "dicomweb":
            msg = "Parquet destination cannot be dicomweb"
            raise ValueError(msg)
        return v


class PixlConfig(BaseModel):
    """Project-specific configuration for Pixl."""

    project: _Project
    tag_operation_files: list[Path]
    destination: _Destination

    @field_validator("tag_operation_files")
    @classmethod
    def _valid_tag_operations(cls, tag_ops_files: list[str]) -> list[Path]:
        if not tag_ops_files or len(tag_ops_files) == 0:
            msg = "There should be at least 1 tag operations file"
            raise ValueError(msg)

        if len(tag_ops_files) > 1:
            msg = "There should currently be at most 1 tag operations file."
            raise ValueError(msg)

        # Pydantic does not appear to automatically check if the file exists
        files = [
            Path(config("PROJECT_CONFIGS_DIR")) / "tag-operations" / tag_ops_file
            for tag_ops_file in tag_ops_files
        ]
        for f in files:
            if not f.exists():
                # For pydantic, you must raise a ValueError (or AssertionError)
                raise ValueError from FileNotFoundError(f)
        return files
