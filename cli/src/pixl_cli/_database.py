"""Interaction with the PIXL database."""

from core.database import Extract, Image
from core.patient_queue.message import Message
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pixl_cli._config import cli_config

connection_config = cli_config["postgres"]

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
        if extract_created:
            return messages

        return _filter_exported_messages(extract, messages, pixl_session)


def _get_or_create_project(project_slug: str, session: Session) -> tuple[Extract, bool]:
    existing_extract = session.query(Extract).filter(Extract.slug == project_slug).one_or_none()
    if existing_extract:
        return existing_extract, False
    new_extract = Extract(slug=project_slug)
    session.add(new_extract)
    return new_extract, True


def _filter_exported_messages(
    extract: Extract, messages: list[Message], session: Session
) -> list[Message]:
    output_messages = []
    for message in messages:
        _, image_exported = _get_image_and_check_exported(extract, message, session)
        if not image_exported:
            output_messages.append(message)
    return output_messages


def _get_image_and_check_exported(
    extract: Extract, message: Message, session: Session
) -> tuple[Image, bool]:
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

    new_image = Image(
        accession_number=message.accession_number,
        study_date=message.study_date,
        mrn=message.mrn,
        extract=extract,
    )
    session.add(new_image)
    return new_image, False
