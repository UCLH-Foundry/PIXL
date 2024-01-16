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
from typing import TYPE_CHECKING

from decouple import config
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Extract, Image

if TYPE_CHECKING:
    from datetime import datetime

url = URL.create(
    drivername="postgresql+psycopg2",
    username=config("PIXL_DB_USER", default="None"),
    password=config("PIXL_DB_PASSWORD", default="None"),
    host=config("PIXL_DB_HOST", default="None"),
    port=config("PIXL_DB_PORT", default=1),
    database=config("PIXL_DB_NAME", default="None"),
)

engine = create_engine(url)


def get_project_slug_from_db(hashed_value: str) -> Image:
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        existing_image = (
            pixl_session.query(Image)
            .filter(
                Image.hashed_identifier == hashed_value,
            )
            .one()
        )

        existing_extract = (
            pixl_session.query(Extract)
            .filter(
                Extract.extract_id == existing_image.extract_id,
            )
            .one()
        )

        return existing_extract.slug


def update_exported_at_and_save(hashed_value: str, date_time: datetime) -> Image:
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        existing_image = (
            pixl_session.query(Image)
            .filter(
                Image.hashed_identifier == hashed_value,
            )
            .one()
        )
        existing_image.exported_at = date_time
        pixl_session.add(existing_image)

        updated_image = (
            pixl_session.query(Image)
            .filter(Image.hashed_identifier == hashed_value, Image.exported_at == date_time)
            .one_or_none()
        )

        return updated_image