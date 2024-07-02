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

from typing import cast

from core.db.models import Extract, Image
from core.patient_queue.message import Message
from loguru import logger
from sqlalchemy import URL, create_engine, not_
from sqlalchemy.orm import Session, sessionmaker

from pixl_cli._config import SERVICE_SETTINGS

connection_config = SERVICE_SETTINGS["postgres"]

url = URL.create(
    drivername="postgresql+psycopg2",
    username=connection_config["username"],
    password=connection_config["password"],
    host=connection_config["host"],
    port=connection_config["port"],
    database=connection_config["database"],
)

engine = create_engine(url)


def filter_exported_or_add_to_db(messages: list[Message], project_slug: str) -> list[Message]:
    """
    Filter exported images for this project, and adds missing extract or images to database.

    :param messages: Initial messages to filter if they already exist
    :param project_slug: project slug to query on
    :return messages that have not been exported
    """
    PixlSession = sessionmaker(engine)
    with PixlSession() as pixl_session, pixl_session.begin():
        extract, extract_created = _get_or_create_project(project_slug, pixl_session)

        return _filter_exported_messages(
            extract, messages, pixl_session, extract_created=extract_created
        )


def _get_or_create_project(project_slug: str, session: Session) -> tuple[Extract, bool]:
    existing_extract = session.query(Extract).filter(Extract.slug == project_slug).one_or_none()
    if existing_extract:
        return existing_extract, False
    new_extract = Extract(slug=project_slug)
    session.add(new_extract)
    return new_extract, True


def _filter_exported_messages(
    extract: Extract, messages: list[Message], session: Session, *, extract_created: bool
) -> list[Message]:
    output_messages = []
    for message in messages:
        _, image_exported = _get_image_and_check_exported(
            extract, message, session, extract_created=extract_created
        )
        if not image_exported:
            output_messages.append(message)
    return output_messages


def _get_image_and_check_exported(
    extract: Extract, message: Message, session: Session, *, extract_created: bool
) -> tuple[Image, bool]:
    if extract_created:
        new_image = _add_new_image_to_session(extract, message, session)
        return new_image, False
    logger.debug("Processing {}", message)
    existing_image = (
        session.query(Image)
        .filter(
            Image.extract == extract,
            Image.accession_number == message.accession_number,
            Image.mrn == message.mrn,
            Image.study_date == message.study_date,
        )
        .one_or_none()
    )

    if existing_image:
        if existing_image.exported_at is not None:
            return existing_image, True
        return existing_image, False

    new_image = _add_new_image_to_session(extract, message, session)
    return new_image, False


def _add_new_image_to_session(extract: Extract, message: Message, session: Session) -> Image:
    new_image = Image(
        accession_number=message.accession_number,
        study_date=message.study_date,
        mrn=message.mrn,
        extract=extract,
    )
    session.add(new_image)
    return new_image


def exported_images_for_project(project_slug: str) -> list[Image]:
    """Given a project, get all images in the DB for that project."""
    PixlSession = sessionmaker(engine)
    with PixlSession() as session:
        return cast(
            list[Image],
            session.query(Image)
            .join(Extract)
            .filter(Extract.slug == project_slug)
            .filter(not_(Image.exported_at.is_(None)))
            .all(),
        )
