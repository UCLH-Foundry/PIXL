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

import logging
import pika

LOGGER = logging.getLogger(__name__)


class PixlProducer(object):
    """
    Generic publisher for RabbitMQ.
    """

    def __init__(self, host, port, queue_name):
        """
        Initialising RabbitMQ service configuration for connection.
        :param str host: URL for the RabbitMQ service
        :param int port: Port on which RabbitMQ service is running
        :param str queue: Name of the queue this producer is to publish on
        """
        self._connection = None
        self._channel = None
        self._queue = None
        self.queue_name = queue_name
        self._host = host
        self._port = port

    def __enter__(self) -> "PixlProducer":
        """Establishes connection to RabbitMQ service."""
        params = pika.ConnectionParameters(
            host=self._host,
            port=self._port
        )
        if self._connection is None or self._connection.is_closed:
            self._connection = pika.BlockingConnection(params)

            if self._channel is None or self._channel.is_closed:
                self._channel = self._connection.channel()
            self._queue = self._channel.queue_declare(queue=self.queue_name)
        LOGGER.info(f"Connected to {self._queue}")
        return self

    def publish(self, msgs: list) -> None:
        """
        Sends a list of messages to a queue.
        :param msgs: list of messages to be sent to queue
        """
        LOGGER.debug(f"Publishing list of messages queue {self.queue_name}")
        if msgs:
            for msg in msgs:
                LOGGER.debug(f"Preparing to publish")
                self._channel.basic_publish(exchange="", routing_key=self.queue_name, body=msg.encode("utf-8"))
                LOGGER.debug(f"Message {msg} published to queue {self.queue_name}")
        else:
            LOGGER.debug("List of messages is empty so nothing will be published to queue.")

    def consume_all(self, timeout_in_seconds) -> tuple():
        """
        Retrieving all messages still on queue for save shutdown.
        :param timeout_in_seconds: Causes shutdown after the timeout (specified in secs)
        :return: Generator to all the messages in the queue that will be auto acknowledge, i.e. delete from queue.
        """
        generator = self._channel.consume(
            queue=self.queue_name,
            auto_ack=True,
            inactivity_timeout=timeout_in_seconds,  # Yields (None, None, None) after this
        )
        LOGGER.debug(f"Returning generator {generator} containing remaining messages for shutdown.")
        return generator

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Shutdown the connection to RabbitMQ service.
        :return:
        """
        self._channel.close()
        self._connection.close()

    def clear_queue(self):
        self._channel.queue_purge(queue=self.queue_name)

    @property
    def connection(self):
        return self._connection

    @property
    def channel(self):
        return self._channel

    @property
    def queue(self):
        return self._queue
