# PIXL Imaging API

The PIXL imaging API processes messages from the imaging queue created by the [CLI](../cli/README.md)
to query images from a dicom server and transfer them to the [`orthanc-raw` instance](../orthanc/orthanc-raw/README.md).

The imaging API will:

- query the [VNA](https://en.wikipedia.org/wiki/Vendor_Neutral_Archive) for existing images
- if a study is not found in the VNA, query
  [PACS](https://en.wikipedia.org/wiki/Picture_archiving_and_communication_system) for existing images.
  The study will only be pulled if it's available
  [ONLINE](https://dicom.nema.org/medical/dicom/2020b/output/chtml/part03/sect_C.4.23.html) (i.e.
  it can be pulled from the Retrieve AE Title)

The imaging API exposes a single HTTP endpoint that expects a JSON-formatted message structured as defined by the
[`Message`](../pixl_core/src/core/patient_queue/message.py) class in `pixl_core/patient_queue`.
On arrival of the input message it will issue a DICOMWeb request to `orthanc-raw`, which then queries the VNA
for the requested imaging study, if it didn't already exist.

## Installation

```bash
python -m pip install --upgrade pip
python -m pip install -e pytest-pixl/
python -m pip install -e "pixl_core/[test]"
python -m pip install -e "pixl_imaging/[test]"
```

## Test


```bash
cd pixl_imaging/tests
pytest
```

## Usage

Usage should be from the CLI driver, which interacts with the endpoint.


## Configuration and database interaction

The database tables are updated using alembic, see the [alembic](alembic) dir for more details.

The `SKIP_ALEMBIC` environmental variable is used to control whether migrations are applied to the database (see variable at '.env.sample' and 'test/.env').

- `SKIP_ALEMBIC` is set to true for tests that do not use the database (e.g. `SKIP_ALEMBIC=true`). Otherwise you probably want to run this.
- If you wanted to test out new migrations from a test/dev deployment on the GAE with data in,
  then you can redeploy just the `imaging-api` container while keeping the `postgres` container up. 
