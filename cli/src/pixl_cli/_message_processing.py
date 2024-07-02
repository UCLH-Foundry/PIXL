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
"""Processing of messages and interaction with rabbitmq."""

from __future__ import annotations

import typing
from time import sleep

import tqdm
from _operator import attrgetter
from core.patient_queue._base import PixlBlockingInterface
from core.patient_queue.producer import PixlProducer
from decouple import config
from loguru import logger

from pixl_cli._config import SERVICE_SETTINGS
from pixl_cli._database import exported_images_for_project, filter_exported_or_add_to_db

if typing.TYPE_CHECKING:
    from core.patient_queue.message import Message


def retry_until_export_count_is_unchanged(
    messages: list[Message], num_retries: int, queues_to_populate: list[str], project_name: str
) -> None:
    """Retry populating messages until there is no change in the number of exported studies."""
    last_exported_count = 0

    total_wait_seconds = config("CLI_RETRY_SECONDS", default=300, cast=int)
    wait_to_display = f"{total_wait_seconds //60} minutes"
    if total_wait_seconds % 60:
        wait_to_display = f"{total_wait_seconds //60} minutes & {total_wait_seconds % 60} seconds"

    logger.info(
        "Retrying extraction every {} until no new extracts are found, max retries: {}",
        wait_to_display,
        num_retries,
    )
    for i in range(1, num_retries + 1):
        _wait_for_queues_to_empty(queues_to_populate)
        logger.info("Waiting 5 minutes for new extracts to be found")
        for _ in tqdm.tqdm(
            range(total_wait_seconds), desc="Waiting for series to be fully processed"
        ):
            sleep(1)

        images = exported_images_for_project(project_name)
        new_last_exported_count = len(images)
        if new_last_exported_count == last_exported_count:
            logger.info(
                "{} studies exported, didn't change between retries",
                new_last_exported_count,
            )
            return
        logger.info(
            "{} studies exported, retrying extraction {}/{}",
            new_last_exported_count - last_exported_count,
            i,
            num_retries,
        )
        last_exported_count = new_last_exported_count
        populate_queue_and_db(queues_to_populate, messages)


def _wait_for_queues_to_empty(queues_to_populate: list[str]) -> None:
    logger.info("Waiting for rabbitmq queues to be empty")
    message_count = _message_count(queues_to_populate)
    while message_count != 0:
        logger.debug(f"{message_count=}, sleeping for a minute")
        sleep(60)
        message_count = _message_count(queues_to_populate)
    logger.info("Queues are empty")


def _message_count(queues_to_populate: list[str]) -> int:
    messages_in_queues = 0
    for queue in queues_to_populate:
        with PixlBlockingInterface(queue_name=queue, **SERVICE_SETTINGS["rabbitmq"]) as rabbitmq:
            messages_in_queues += rabbitmq.message_count
    return messages_in_queues


def populate_queue_and_db(queues: list[str], messages: list[Message]) -> None:
    """
    Populate queues with messages,
    for imaging queue update the database and filter out exported studies.
    """
    for queue in queues:
        sorted_messages = sorted(messages, key=attrgetter("study_date"))
        # For imaging, we don't want to query again for images that have already been exported
        if queue == "imaging" and messages:
            logger.info("Filtering out exported images and uploading new ones to the database")
            sorted_messages = filter_exported_or_add_to_db(
                sorted_messages, messages[0].project_name
            )
        with PixlProducer(queue_name=queue, **SERVICE_SETTINGS["rabbitmq"]) as producer:
            producer.publish(sorted_messages)
