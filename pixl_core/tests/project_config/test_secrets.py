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

import pytest
from core.project_config.secrets import AzureKeyVault


class MockAzureKeyVault(AzureKeyVault):
    """Mock AzureKeyVault class for testing."""

    def __init__(self) -> None:
        """Create a mock instance of AzureKeyVault."""

    def fetch_secret(self, secret_name: str) -> str:
        """Mock method to fetch a secret from the Azure Key Vault."""
        return secret_name + "-mock-secret"


@pytest.fixture()
def azure_keyvault():
    """Create an instance of AzureKeyVault for testing."""
    return MockAzureKeyVault()


def test_keyvault_constructor_checks_envvars():
    """Test that the constructor checks for the required environment variables."""
    with pytest.raises(OSError, match="AZURE_CLIENT_ID"):
        AzureKeyVault()


def test_fetch_secret(azure_keyvault):
    """Test that we can fetch secrets with the AzureKeyVault class."""
    assert azure_keyvault.fetch_secret("test") == "test-mock-secret"
