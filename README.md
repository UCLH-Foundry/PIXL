[![pixl-ci](https://github.com/SAFEHR-data/PIXL/actions/workflows/main.yml/badge.svg)](https://github.com/SAFEHR-data/PIXL/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/SAFEHR-data/PIXL/graph/badge.svg?token=99CHF3ZCAW)](https://codecov.io/gh/SAFEHR-data/PIXL)

# PIXL

PIXL Image eXtraction Laboratory

`PIXL` is a system for extracting, linking and de-identifying DICOM imaging data, structured EHR data and free-text data from radiology reports at UCLH.
Please see the [rolling-skeleton]([https://github.com/SAFEHR-data/the-rolling-skeleton=](https://github.com/SAFEHR-data/the-rolling-skeleton/blob/main/docs/design/100-day-design.md)) for more details.

PIXL is intended run on one of the [GAE](https://github.com/SAFEHR-data/Book-of-FlowEHR/blob/main/glossary.md#gaes)s and comprises
several services orchestrated by [Docker Compose](https://docs.docker.com/compose/).

To get access to the GAE, [see the documentation on Slab](https://uclh.slab.com/posts/gae-access-7hkddxap)

## Installation

Install the PIXL Python modules by running the following commands from the top-level `PIXL/` directory:

```shell
python -m pip install -e pixl_core/
python -m pip install -e cli/
```

Note, the CLI currently [needs to be installed in editable mode](https://github.com/SAFEHR-data/PIXL/issues/318).

## Development

[Follow the developer setup instructions](./docs/setup/developer.md).

Before raising a PR, make sure to **run the tests** for every PIXL module, not just the one you
have been working on. In addition, make sure to [have `pre-commit` installed](/docs/setup/developer.md#linting)
to automatically check your code before committing.


## Design

[`docs/design`](./docs/design/) contains the design documentation for the PIXL system.

## Services

### [PIXL core](./pixl_core/README.md)

The `core` module contains the functionality shared by the other PIXL modules.

### [PIXL CLI](./cli/README.md)

Primary interface to the PIXL system.

### [Hasher API](./hasher/README.md)

HTTP API to securely hash an identifier using a key stored in Azure Key Vault.

### [Orthanc](./orthanc/README.md)

#### [Orthanc Raw](./orthanc/orthanc-raw/README.md)

A DICOM node which receives images from the upstream hospital systems and acts as cache for PIXL.

#### [Orthanc Anon](./orthanc/orthanc-anon/README.md)

A DICOM node which wraps our de-identifcation process and uploading of the images to their final
destination.

#### [PIXL DICOM de-identifier](./pixl_dcmd/README.md)

Provides helper functions for de-identifying DICOM data

### PostgreSQL

RDBMS which stores DICOM metadata, application data and anonymised patient record data.

### [Export API](pixl_export/README.md)

HTTP API to export files (parquet and DICOM) from UCLH to endpoints.

### [Image Extractor](./pixl_imaging/README.md)

HTTP API to process messages from the `imaging` queue and populate the raw orthanc instance with images from PACS/VNA.

## Setup

### 0. [UCLH infrastructure setup](./docs/setup/uclh-infrastructure-setup.md)

### 1. Choose deployment environment

This is one of `dev|test|staging|prod` and referred to as `<environment>` in the docs.

### 2. Initialise environment configuration

Create a local `.env` file in the _PIXL_ directory:

```bash
cp .env.sample .env
```

Add the missing configuration values to the new files:

#### Credentials

- `PIXL_DB_`*
These are credentials for the containerised PostgreSQL service and are set in the official PostgreSQL image.
Use a strong password for `prod` deployment but the only requirement for other environments is consistency as several services interact with the database.

#### Ports

Most services need to expose ports that must be mapped to ports on the host. The host port is specified in `.env`
Ports need to be configured such that they don't clash with any other application running on that GAE.

#### Storage size

The maximum storage size of the `orthanc-raw` instance can be configured through the
`ORTHANC_RAW_MAXIMUM_STORAGE_SIZE` environment variable in `.env`. This limits the storage size to
the specified value (in MB). When the storage is full [Orthanc will automatically recycle older
studies in favour of new ones](https://orthanc.uclouvain.be/book/faq/features.html#id8).


### 3. Configure a new project

To configure a new project, follow these steps:

1. Create a new `git` branch from `main`

    ```shell
    git checkout main
    git pull
    git switch -c <branch-name>
    ```

1. Copy the `template_config.yaml` file to a new file in the `projects/config` directory and fill
   in the details.
1. The filename of the project config should be `<project-slug>`.yaml

    >[!NOTE]
    > The project slug should match the [slugify](https://github.com/un33k/python-slugify)-ed project name in the `extract_summary.json` log file!

2. [Open a PR in PIXL](https://github.com/SAFEHR-data/PIXL/compare) to merge the new project config into `main`

#### The config YAML file

<details><summary>The config YAML file</summary>
<p>
The configuration file defines:

- Project name: the `<project-slug>` name of the Project
- The DICOM dataset modalities to retain (e.g. `["DX", "CR"]` for X-Ray studies)
- The [anonymisation operations](/pixl_dcmd/README.md#tag-scheme-anonymisation) to be applied to the DICOM tags,
  by providing a file path to one or multiple YAML files.
  We currently allow two types of files:
    - `base`: the base set of DICOM tags to be retained in the anonymised dataset
    - `manufacturer_overrides`: any manufacturer-specific overrides to the base set of DICOM tags. This is useful for
        manufacturers that store sensitive information in non-standard DICOM tags. Multiple manufacturers
        can be specified in the YAML file as follows:

    ```yaml
    - manufacturer: "Philips"
      tags:
      - group: 0x2001
        element: 0x1003
        op: "keep"
        # ...
    - manufacturer: "Siemens"
      tags:
      - group: 0x0019
        element: 0x100c
        op: "keep"
        # ...
    ```

- The endpoints used to upload the anonymised DICOM data and the public and radiology
  [parquet files](./docs/file_types/parquet_files.md). We currently support the following endpoints:
    - `"none"`: no upload
    - `"ftps"`: a secure FTP server (for both _DICOM_ and _parquet_ files)
    - `"dicomweb"`: a DICOMweb server (for _DICOM_ files only).
      Requires the `DICOMWEB_*` environment variables to be set in `.env`
    - `"xnat"`: an [XNAT](https://www.xnat.org/) instance (for _DICOM_ files only)
    <!-- - `"azure"`: a secure Azure Dicom web service (for both _DICOM_ and _parquet_ files) -->
    <!--   Requires the `AZURE_*` environment variables to be set in `.env` -->
</p>
</details> 

#### Project secrets

<details><summary>Project secrets</summary>
<p>

Any credentials required for uploading the project's results should be stored in an **Azure Key Vault**
(set up instructions below).
PIXL will query this key vault for the required secrets at runtime. This requires the following
environment variables to be set so that PIXL can connect to the key vault:

- `EXPORT_AZ_CLIENT_ID`: the service principal's client ID, mapped to `AZURE_CLIENT ID` in `docker-compose`
- `EXPORT_AZ_CLIENT_PASSWORD`: the password, mapped to `AZURE_CLIENT_SECRET` in `docker-compose`
- `EXPORT_AZ_TENANT_ID`: ID of the service principal's tenant. Also called its 'directory' ID. Mapped to `AZURE_TENANT_ID` in `docker-compose`
- `EXPORT_AZ_KEY_VAULT_NAME` the name of the key vault, used to connect to the correct key vault

These variables can be set in the `.env` file.
For testing, they can be set in the `test/.secrets.env` file.
For dev purposes find the `pixl-dev-secrets.env` note on LastPass for the necessary values.

If an Azure Keyvault hasn't been set up yet, follow [these instructions](./docs/setup/azure-keyvault.md).

A second Azure Keyvault is used to store hashing keys and salts for the `hasher` service.
This kevyault is configured with the following environment variables:

- `HASHER_API_AZ_CLIENT_ID`: the service principal's client ID, mapped to `AZURE_CLIENT ID` in `docker-compose`
- `HASHER_API_AZ_CLIENT_PASSWORD`: the password, mapped to `AZURE_CLIENT_SECRET` in `docker-compose`
- `HASHER_API_AZ_TENANT_ID`: ID of the service principal's tenant. Also called its 'directory' ID. Mapped to `AZURE_TENANT_ID` in `docker-compose`
- `HASHER_API_AZ_KEY_VAULT_NAME` the name of the key vault, used to connect to the correct key vault

See the [hasher documentation](./hasher/README.md) for more information.
</p>
</details> 

## Run

### Start

From the _PIXL_ directory:

```shell
pixl dc up
```

Once the services are running, you can interact with the services using the [`pixl` CLI](./cli/README.md).

### Stop

From the _PIXL_ directory:

```shell
pixl dc down  # --volumes to remove all data volumes
```

## Analysis

The number of DICOM instances in the raw Orthanc instance can be accessed from
`http://<pixl_host>:<ORTHANC_RAW_WEB_PORT>/ui/app/#/settings` and similarly with
the Orthanc Anon instance, where `pixl_host` is the host of the PIXL services
and `ORTHANC_RAW_WEB_PORT` is defined in `.env`.

The imaging export progress can be interrogated by connecting to the PIXL
database with a database client (e.g. [DBeaver](https://dbeaver.io/)), using
the connection parameters defined in `.env`.

## Assumptions

PIXL data extracts include the below assumptions

- (MRN, Accession number) is unique identifier for a report/DICOM study pair
- Patients have a single _relevant_ MRN

## File journey overview

Files that are present at each step of the pipeline.

A more detailed description of the relevant file types is available in [`docs/file_types/parquet_files.md`](./docs/file_types/parquet_files.md).

### Resources in source repo (for test only)

```
test/resources/omop/public /*.parquet
....................private/*.parquet
....................extract_summary.json
```

### OMOP ES extract dir (input to PIXL)

EXTRACT_DIR is the directory passed to `pixl populate` as the input `PARQUET_PATH` argument.

```
EXTRACT_DIR/public /*.parquet
............private/*.parquet
............extract_summary.json
```

### PIXL Export dir (PIXL intermediate)

The directory where PIXL will copy the public OMOP extract files (which now contain
the radiology reports) to.
These files will subsequently be uploaded to the `parquet` destination specified in the
[project config](#3-configure-a-new-project).

```
EXPORT_ROOT/PROJECT_SLUG/all_extracts/EXTRACT_DATETIME/radiology/IMAGE_LINKER.parquet
....................................................../omop/public/*.parquet
```

This directory is currently located in `projects/exports` relative to the source code root.

[Further discussion about docker permissions and the exports directory is found here](docs/setup/docker_perms.md)

### Destination

#### FTP server

If the `parquet` destination is set to `ftps`, the public extract files and radiology report will
be uploaded to the FTP server at the following path:

```
FTPROOT/PROJECT_SLUG/EXTRACT_DATETIME/parquet/radiology/radiology.parquet
..............................................omop/public/*.parquet
```

## :octocat: Cloning repository
* Generate your SSH keys as suggested [here](https://docs.github.com/en/github/authenticating-to-github/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)
* Clone the repository by typing (or copying) the following lines in a terminal
```
git clone git@github.com:SAFEHR-data/PIXL.git
```

