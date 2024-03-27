# The PIXL database

PIXL uses a [postgres database](../../postgres/README.md) to 

- Add hashed identifiers along with the originals for DICOM images (in `pixl_dcmd`)
- Keep track of the export status of images (in `core.uploader`)

