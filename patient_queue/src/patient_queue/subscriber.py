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

import os
import aio_pika
import logging
from typing import Any
from typing import Callable

from token_buffer import TokenBucket

LOGGER = logging.getLogger(__name__)


class PixlConsumer:
    """
    Connector to RabbitMQ. Consumes messages from a queue that specify patients for
    which EHR demographic data needs to be retrieved.
    """

    def __init__(self, queue: str, host: str, port: int, token_bucket: TokenBucket) -> None:
        """
        Creating connection to RabbitMQ queue.
        :param queue: Name of the queue to connect to.
        :param port: Port the queue is provided through (i.e. RabbitMQ port)
        """
        print(os.environ['RABBITMQ_DEFAULT_USER'])
        self.token_bucket = token_bucket
        self._url = (f"amqp://{os.environ['RABBITMQ_DEFAULT_USER']}" 
                     f":{os.environ['RABBITMQ_DEFAULT_PASS']}@{host}:{port}/")
        self._queue_name = queue

    async def __aenter__(self) -> "PixlConsumer":
        """Establishes connection to queue."""
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        self._queue = await self._channel.declare_queue(self._queue_name)
        return self

    def __await__(self):
        return self.__aenter__()

    async def run(self, callback: Callable) -> None:
        """Creates loop that waits for messages from producer and processes them as they appear.
        :param callback: method to be called when new message arrives that needs to be processed
        """
        async with self._queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    if self.token_bucket is not None:
                        if self.token_bucket.has_token:
                            callback(message.body)
                            await message.ack()
                        else:
                            await message.reject(requeue=True)
                except Exception as e:  # noqa
                    LOGGER.error(
                        f"Failed to process {message.body.decode()} due to\n{e}\n"
                        f"Not re-queuing message"
                    )
                    await message.reject(requeue=False)

    def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        pass
