#  Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
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

"""Subscriber for RabbitMQ"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import aio_pika
from decouple import config

from core.exceptions import (
    PixlDiscardError,
    PixlOutOfHoursError,
    PixlRequeueMessageError,
    PixlStudyNotInPrimaryArchiveError,
)
from core.patient_queue._base import PixlQueueInterface
from core.patient_queue.message import deserialise
from core.patient_queue.producer import PixlProducer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aio_pika.abc import AbstractIncomingMessage
    from typing_extensions import Self

    from core.patient_queue.message import Message
    from core.token_buffer.tokens import TokenBucket

from loguru import logger


class PixlConsumer(PixlQueueInterface):
    """Connector to RabbitMQ. Consumes messages from a queue"""

    def __init__(
        self,
        queue_name: str,
        token_bucket: TokenBucket,
        token_bucket_key: str,
        callback: Callable[[Message], Awaitable[None]],
    ) -> None:
        """
        Creating connection to RabbitMQ queue
        :param token_bucket: Token bucket for the queue
        """
        super().__init__(queue_name=queue_name)
        self.token_bucket = token_bucket
        self.token_bucket_key = token_bucket_key
        self._callback = callback

    @property
    def _url(self) -> str:
        return f"amqp://{self._username}:{self._password}@{self._host}:{self._port}/"

    async def __aenter__(self) -> Self:
        """Establishes connection to queue."""
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        # Set number of messages in flight
        max_in_flight = config("PIXL_MAX_MESSAGES_IN_FLIGHT", cast=int)
        logger.info("Pika will consume up to {} messages concurrently", max_in_flight)
        await self._channel.set_qos(prefetch_count=max_in_flight)
        self._queue = await self._channel.declare_queue(
            self.queue_name,
            durable=True,
            arguments={"x-max-priority": 5},
        )
        return self

    async def _process_message(self, message: AbstractIncomingMessage) -> None:
        if not self.token_bucket.has_token(key=self.token_bucket_key):
            await asyncio.sleep(1)
            await message.reject(requeue=True)
            return

        pixl_message: Message = deserialise(message.body)
        logger.debug("Picked up from queue: {}", pixl_message.identifier)
        try:
            await self._callback(pixl_message)
        except PixlRequeueMessageError as requeue:
            logger.trace("Requeue message: {} from {}", pixl_message.identifier, requeue)
            await asyncio.sleep(1)
            await message.reject(requeue=True)
        except PixlStudyNotInPrimaryArchiveError as discard:
            logger.info(
                "Discard message: {} from {}. Sending to secondary imaging queue with priority {}.",
                pixl_message.identifier,
                discard,
                message.priority,
            )
            with PixlProducer(
                queue_name="imaging-secondary",
                host=config("RABBITMQ_HOST"),
                port=config("RABBITMQ_PORT", cast=int),
                username=config("RABBITMQ_USERNAME"),
                password=config("RABBITMQ_PASSWORD"),
            ) as producer:
                producer.publish([pixl_message], priority=message.priority)
            await message.reject(requeue=False)
        except PixlOutOfHoursError as nack_requeue:
            logger.trace(
                "Nack and requeue message: {} from {}", pixl_message.identifier, nack_requeue
            )
            await asyncio.sleep(10)
            await message.nack(requeue=True)
        except PixlDiscardError as exception:
            logger.warning("Failed message {}: {}", pixl_message.identifier, exception)
            await (
                message.ack()
            )  # ack so that we can see rate of message processing in rabbitmq admin
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to process {}. Not re-queuing message",
                pixl_message.identifier,
            )
            await (
                message.ack()
            )  # ack so that we can see rate of message processing in rabbitmq admin
        else:
            logger.success("Finished message {}", pixl_message.identifier)
            await message.ack()

    async def run(self) -> None:
        """Processes messages from queue asynchronously."""
        await self._queue.consume(self._process_message)

    async def __aexit__(self, *args: object, **kwargs: Any) -> None:
        """Requirement for the asynchronous context manager"""
