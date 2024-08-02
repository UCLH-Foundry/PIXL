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

"""Interaction with the PIXL database."""

from decouple import config  # type: ignore [import-untyped]
import pydicom
from pydicom.uid import generate_uid, UID
from sqlalchemy.orm.session import Session

from core.db.models import Image, Extract
from sqlalchemy import URL, create_engine, exists
from sqlalchemy.orm import sessionmaker, exc

from pixl_dcmd._dicom_helpers import StudyInfo

url = URL.create(
    drivername="postgresql+psycopg2",
    username=config("PIXL_DB_USER", default="None"),
    password=config("PIXL_DB_PASSWORD", default="None"),
    host=config("PIXL_DB_HOST", default="None"),
    port=config("PIXL_DB_PORT", default=1),
    database=config("PIXL_DB_NAME", default="None"),
)

engine = create_engine(url)


def get_uniq_pseudo_study_uid_and_update_db(
    project_slug: str, study_info: StudyInfo
) -> UID:
    """
    Checks if record (slug, study UID) exists in the database,
    gets the pseudo_study_uid if it is not None or records a new, unique one.
    Returns the pseudo_study_uid.
    """
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        existing_image = get_unexported_image(
            project_slug,
            study_info,
            pixl_session,
        )
        if existing_image.pseudo_study_uid is None:
            pseudo_study_uid = generate_uid()
            while not is_unique_pseudo_study_uid(pseudo_study_uid, pixl_session):
                pseudo_study_uid = generate_uid()
            add_pseudo_study_uid_to_db(existing_image, pseudo_study_uid, pixl_session)
        else:
            pseudo_study_uid = existing_image.pseudo_study_uid
        return UID(pseudo_study_uid, validation_mode=pydicom.config.RAISE)


def add_pseudo_study_uid_to_db(
    existing_image: Image, pseudo_study_uid: str, pixl_session: Session
) -> None:
    """
    Add a pseudo study UID generated during anonymisation to the database
    for an existing image generated by populate command.
    """
    existing_image.pseudo_study_uid = pseudo_study_uid
    pixl_session.add(existing_image)


def is_unique_pseudo_study_uid(pseudo_study_uid: str, pixl_session: Session) -> bool:
    """
    Check that random uid generated is not already in the database.
    """
    return not pixl_session.query(
        exists().where(Image.pseudo_study_uid == pseudo_study_uid)
    ).scalar()


def get_unexported_image(
    project_slug: str,
    study_info: StudyInfo,
    pixl_session: Session,
) -> Image:
    """
    Get an existing, non-exported (for this project) image record from the database
    identified by the study UID. If no result is found, retry with querying on
    MRN + accession number. If this fails as well, raise a PixlDiscardError.
    """
    try:
        existing_image: Image = (
            pixl_session.query(Image)
            .join(Extract)
            .filter(
                Extract.slug == project_slug,
                Image.study_uid == study_info.study_uid,
                Image.exported_at == None,  # noqa: E711
            )
            .one()
        )
    # If no image is found by study UID, try MRN + accession number
    except exc.NoResultFound:
        existing_image = (
            pixl_session.query(Image)
            .join(Extract)
            .filter(
                Extract.slug == project_slug,
                Image.mrn == study_info.mrn,
                Image.accession_number == study_info.accession_number,
                Image.exported_at == None,  # noqa: E711
            )
            .one()
        )
    return existing_image
