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

from datetime import datetime

from decouple import config
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import Image

url = URL.create(
    drivername="postgresql+psycopg2",
    username=config("PIXL_DB_USER", default="None"),
    password=config("PIXL_DB_PASSWORD", default="None"),
    host=config("PIXL_DB_HOST", default="None"),
    port=config("PIXL_DB_PORT", default=1),
    database=config("PIXL_DB_NAME", default="None"),
)

engine = create_engine(url)


def have_already_exported_image(pseudo_study_uid: str) -> bool:
    """Check if the given image has already been exported."""
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        existing_image = _query_existing_image(pixl_session, pseudo_study_uid)
        return existing_image.exported_at is not None


def update_exported_at(pseudo_study_uid: str, date_time: datetime) -> None:
    """Update the `exported_at` field for an image in the PIXL database"""
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        existing_image = _query_existing_image(pixl_session, pseudo_study_uid)
        existing_image.exported_at = date_time
        pixl_session.add(existing_image)


def _query_existing_image(pixl_session: Session, pseudo_study_uid: str) -> Image:
    existing_image: Image = (
        pixl_session.query(Image)
        .filter(
            Image.pseudo_study_uid == pseudo_study_uid,
        )
        .one()
    )
    return existing_image
