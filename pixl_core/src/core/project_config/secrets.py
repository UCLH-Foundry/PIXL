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

"""Handles fetching of project secrets from the Azure Keyvault"""

from __future__ import annotations

import subprocess
from functools import lru_cache

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from decouple import config  # type: ignore [import-untyped]


class AzureKeyVault:
    """Handles fetching of project secrets from the Azure Keyvault"""

    def __init__(self) -> None:
        """
        Initialise the AzureKeyVault instance

        Creates an EnvironmentCredential via AzureDefaultCredential to connect with a
        ServicePrincipal and secret configured via environment variables.

        This requires the following environment variables to be set, which will be picked up by the
        Azure SDK:
        - AZURE_CLIENT_ID
        - AZURE_CLIENT_SECRET
        - AZURE_TENANT_ID
        - AZURE_KEY_VAULT_NAME
        """
        self._check_envvars()
        self.name = config("AZURE_KEY_VAULT_NAME")

    def fetch_secret(self, secret_name: str) -> str:
        """
        Fetch a secret from the Azure Key Vault instance specified in the environment variables.
        :param secret_name: the name of the secret to fetch
        :return: the requested secret's value
        """
        return _fetch_secret(self.name, secret_name)

    def create_secret(self, secret_name: str, secret_value: str) -> None:
        """
        Create a secret in the Azure Key Vault instance specified in the environment variables.
        :param secret_name: the name of the secret to create
        :param secret_value: the value of the secret to create
        """
        client = _setup_client(self.name)
        client.set_secret(secret_name, secret_value)

    def _check_envvars(self) -> None:
        """
        Check if the required environment variables are set.
        These need to be set system-wide, as the Azure SDK picks them up from the environment.
        :raises OSError: if any of the environment variables are not set
        """
        _check_system_envvar("AZURE_CLIENT_ID")
        _check_system_envvar("AZURE_CLIENT_SECRET")
        _check_system_envvar("AZURE_TENANT_ID")
        _check_system_envvar("AZURE_KEY_VAULT_NAME")


def _check_system_envvar(var_name: str) -> None:
    """Check if an environment variable is set system-wide"""
    error_msg = f"Environment variable {var_name} not set"
    if not subprocess.check_output(f"echo ${var_name}", shell=True).decode().strip():  # noqa: S602
        raise OSError(error_msg)


def _setup_client(kv_name: str) -> SecretClient:
    key_vault_uri = f"https://{kv_name}.vault.azure.net"
    credentials = DefaultAzureCredential()
    return SecretClient(vault_url=key_vault_uri, credential=credentials)


@lru_cache
def _fetch_secret(kv_name: str, secret_name: str) -> str:
    """
    Fetch a secret from the Azure Key Vault instance specified in the environment variables.
    This method is cached to avoid unnecessary calls to the Key Vault using the LRU (least
    recently used) strategy.

    This helper is intentionally defined outside the Azure Keyvault to prevent memory leaks (see
    ruff rule B019).

    For caching to work, all parameters need to be hashable, so we cannot pass in the client as
    input, but instead create it in the function.

    :param kv_name: name of the Azure Key Vault instance
    :param secret_name: the name of the secret to fetch
    :return: the requested secret's value
    """
    client = _setup_client(kv_name)

    try:
        secret = client.get_secret(secret_name).value
    # Raise a ValueError if the secret is not found so we can handle it downstream
    except ResourceNotFoundError as e:
        msg = f"Secret {secret_name} not found in Azure Key Vault"
        raise ValueError(msg) from e

    if secret is None:
        msg = f"Azure Key Vault secret {secret_name} is None"
        raise ValueError(msg)

    return str(secret)
