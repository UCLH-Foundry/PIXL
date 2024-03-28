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


from pathlib import Path

import pytest
import yaml
from core.project_config import PixlConfig, load_project_config
from core.project_config.tag_operations import load_tag_operations
from decouple import config
from pydantic import ValidationError

PROJECT_CONFIGS_DIR = Path(config("PROJECT_CONFIGS_DIR"))
TEST_CONFIG = "test-extract-uclh-omop-cdm"


def test_config_from_file():
    """Test whether config file is correctly parsed and validated."""
    project_config = load_project_config(TEST_CONFIG)

    assert project_config.project.name == "test-extract-uclh-omop-cdm"
    assert project_config.project.modalities == ["DX", "CR"]
    assert project_config.destination.dicom == "ftps"
    assert project_config.destination.parquet == "ftps"


@pytest.fixture()
def base_yaml_data():
    """Good data (excluding optional fields)"""
    return {
        "project": {"name": "myproject", "modalities": ["DX", "CR"]},
        "tag_operation_files": {
            "base": ["test-extract-uclh-omop-cdm.yaml"],
            "manufacturer_overrides": "mri-diffusion.yaml",
        },
        "destination": {"dicom": "ftps", "parquet": "ftps"},
    }


def test_base_is_valid(base_yaml_data):
    """Before anything else, check that the unaltered baseline validates ok."""
    PixlConfig.model_validate(base_yaml_data)


def test_parquet_dicom_fails(base_yaml_data):
    """
    Test that the config validation fails for non-valid values: 'dicomweb' not allowed for
    parquet destionation
    """
    config_data = base_yaml_data
    config_data["destination"]["parquet"] = "dicomweb"
    with pytest.raises(ValidationError):
        PixlConfig.model_validate(config_data)


def test_invalid_destinations(base_yaml_data):
    """Test that the config validation fails for invalid destinations."""
    config_data = base_yaml_data
    config_data["destination"]["dicom"] = "nope"
    config_data["destination"]["parquet"] = "nope"
    with pytest.raises(ValidationError):
        PixlConfig.model_validate(config_data)


def test_invalid_paths(base_yaml_data):
    """Test that the config validation fails for invalid tag-operation paths."""
    config_data_wrong_base = base_yaml_data
    config_data_wrong_base["tag_operation_files"]["base"][0] = "/i/dont/exist.yaml"
    with pytest.raises(ValidationError):
        PixlConfig.model_validate(config_data_wrong_base)


@pytest.mark.parametrize(("yaml_file"), PROJECT_CONFIGS_DIR.glob("*.yaml"))
def test_all_real_configs(yaml_file):
    """Test that all production configs are valid"""
    load_project_config(yaml_file.stem)


def test_load_tag_operations():
    """Test whether tag operations are correctly loaded."""
    project_config = load_project_config(TEST_CONFIG)
    assert load_tag_operations(project_config)


@pytest.mark.parametrize(("yaml_file"), PROJECT_CONFIGS_DIR.glob("*.yaml"))
def test_all_real_tagoperations(yaml_file):
    """Test that all production configs are valid"""
    project_config = load_project_config(yaml_file.stem)
    load_tag_operations(project_config)


def test_load_tag_operations_no_manufacturer_overrides(base_yaml_data):
    """Test whether tag operations are correctly loaded when no overrides are present."""
    # Arrange
    base_yaml_data["tag_operation_files"]["manufacturer_overrides"] = None
    project_config = PixlConfig.model_validate(base_yaml_data)

    # Act
    tag_operations = load_tag_operations(project_config)

    # Assert
    assert tag_operations.manufacturer_overrides is None


@pytest.fixture()
def invalid_base_tags(tmp_path_factory, base_yaml_data) -> PixlConfig:
    """TagOperations with invalid base tags."""
    base_tags = [
        {"I": "tag1", "am": 0x001, "not": 0x1000, "valid": "delete"},
    ]

    tmpdir = tmp_path_factory.mktemp("tag-operations")
    base_tags_path = tmpdir / "base.yaml"
    with base_tags_path.open("w") as f:
        f.write(yaml.dump(base_tags))

    invalid_base_yaml_data = base_yaml_data
    invalid_base_yaml_data["tag_operation_files"]["base"] = [str(base_tags_path)]
    return PixlConfig.model_validate(invalid_base_yaml_data)


def test_invalid_base_tags_fails(invalid_base_tags):
    """Test that invalid base tags raise an error."""
    with pytest.raises(ValidationError):
        load_tag_operations(invalid_base_tags)


FILTER_SET_0 = None
FILTER_SET_1 = []
FILTER_SET_2 = ["nak", "Badg"]
FILTER_SET_BROKEN = ["", "Badg"]


@pytest.mark.parametrize(
    ("series_filters", "test_series_desc", "expect_exclude"),
    [
        # Missing or empty filter set: allow everything
        (FILTER_SET_0, "Snake", False),
        (FILTER_SET_0, "Badger", False),
        (FILTER_SET_0, "Mushroom", False),
        (FILTER_SET_1, "Snake", False),
        (FILTER_SET_1, "Badger", False),
        (FILTER_SET_1, "Mushroom", False),
        # A non-empty filter set, a match to any in the set means exclude
        (FILTER_SET_2, "Snake", True),
        (FILTER_SET_2, "Badger", True),
        (FILTER_SET_2, "Mushroom", False),
        # And then some weird cases.
        # Empty series string never gets excluded
        (FILTER_SET_2, "", False),
        # Empty exclude string matches everything - not ideal but let's fix it when we decide
        # what to do about regexes etc.
        (FILTER_SET_BROKEN, "Mushroom", True),
    ],
)
def test_series_filtering(base_yaml_data, series_filters, test_series_desc, expect_exclude):
    """Check that series filters work, including some edge cases. No regexes yet."""
    if series_filters is not None:
        base_yaml_data["series_filters"] = series_filters
    cfg = PixlConfig.model_validate(base_yaml_data)
    assert cfg.is_series_excluded(test_series_desc) == expect_exclude
