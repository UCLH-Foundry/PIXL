# Azure Keyvault setup

_This is done for the \_UCLH_DIF\_ `dev` tenancy, will need to be done once in the _UCLHAZ_ `prod`
tenancy when ready to deploy to production._

This Key Vault and secret must persist any infrastructure changes so should be separate from disposable
infrastructure services. A [Service Principal](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication-on-premises-apps)
is required to connect to the Key Vault.

The application uses the Service Principal and password to [authenticate with Azure via environment
variables](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.environmentcredential?view=azure-python).

The Key Vault and Service Principal have already been created for the `dev` environment and details
are stored in the `pixl-dev-secrets.env` note in the shared PIXL folder on _LastPass_.

The process for doing so using the `az` CLI tool is described below.
This process must be repeated for `staging` & `prod` environments.

### Step 1

Create the Azure Key Vault in an appropriate resource group:

```bash
az keyvault create --resource-group <resource-group-name> --name <key-vault-name> --location "UKSouth"
```

### Step 2

Create Service Principal & grant access as per

```bash
az ad sp create-for-rbac -n pixl-secrets --skip-assignment
```

This will produce the following output

```json
{
    "appId": "<generated-app-ID>",
    "displayName": "<app-name>",
    "name": "http://<app-name>",
    "password": "<generated-password>",
    "tenant": "<tenant-ID>"
}
```

### Step 3

Assign correct permissions to the newly created ServicePrincipal

```bash
az keyvault set-policy --name <key-vault-name> --spn <generated-app-ID> --secret-permissions backup delete get list set
```

### Step 4

Create a secret and store in the Key Vault

Use Python to create a secret:

```python
import secrets
secrets.token_urlsafe(32)
```

copy the secret and paste as <secret-value> below

```bash
az keyvault secret set --vault-name "<key-vault-name>" --name "<secret-name>" --value "<secret-value>"
```

### Step 5

Save credentials in `.secrets.env` and a LastPass `PIXL Keyvault <project-slug> secrets` note.

```
EXPORT_AZ_CLIENT_ID=<generated-app-ID>
EXPORT_AZ_CLIENT_PASSWORD=<generated-password>
EXPORT_AZ_TENANT_ID=<tenant-ID>
EXPORT_AZ_KEY_VAULT_NAME=<key-vault-name>
