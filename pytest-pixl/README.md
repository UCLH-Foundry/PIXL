# PIXL pytest plugin

Installable `pytest` plugin module providing common test fixtures used throughout PIXL.

## Available fixtures

### `ftps_server`

Spins up an FTPS server with _implicit SSL_ enabled on the local machine. Configurable by setting
the following environment variables:

- `FTP_HOST`: URL to the FTPS server
- `FTP_PORT`: port on which the FTPS server is listening
- `FTP_USER_NAME`: name of user with access to the FTPS server
- `FTP_USER_PASSWORD`: password for the authorised user

## Available testing utilities

- `dicom.write_volume`: write a volume of MRI DICOMs for testing