import os
from pathlib import Path
from typing import Any

import pandas as pd

import click
import pika
from pixl_cli._logging import logger, set_log_level
from pixl_cli._utils import clear_file, string_is_non_empty
from requests import post
import yaml


def _load_config(filename: str = "pixl_config.yml") -> dict:
    """CLI configuration generated from a .yaml"""

    if not Path(filename).exists():
        raise IOError(
            f"Failed to find {filename}. It must be present "
            f"in the current working directory"
        )

    with open(filename, "r") as config_file:
        config_dict = yaml.load(config_file, Loader=yaml.FullLoader)
    return dict(config_dict)


config = _load_config()


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(debug: bool) -> None:
    """Main CLI entrypoint"""
    set_log_level("WARNING" if not debug else "DEBUG")


@cli.command()
@click.argument("csv_filename", type=click.Path(exists=True))
@click.option(
    "--queues",
    default="ehr,pacs",
    show_default=True,
    help="Comma seperated list of topics to populate with messages generated from the "
    ".csv file. In the format <tenant>/<namespace>/<topic>",
)
@click.option(
    "--no-restart",
    is_flag=True,
    show_default=True,
    default=False,
    help="Do not restart from a saved state. Otherwise will use "
    "<topic-name>.csv files if they are present to rebuild the state.",
)
def populate(csv_filename: str, queues: str, no_restart: bool) -> None:
    """
    Create the PIXL driver by populating the queues and setting the rate parameters
    for the token buckets
    """
    logger.info(f"Populating queue from {csv_filename}")

    all_messages = messages_from_csv(Path(csv_filename))
    for topic in queues.split(","):

        cached_state_filepath = state_filepath_for_queue(topic)
        if cached_state_filepath.exists() and not no_restart:
            messages = messages_from_state(cached_state_filepath)
        else:
            messages = all_messages

        logger.info(f"Sending {len(messages)} messages")
        messages.send(topic)


def messages_from_state(filepath: Path) -> "Messages":
    logger.info(f"Extracting messages from {filepath}")

    inform_user_that_queue_will_be_populated_from(filepath)
    messages = Messages.from_state_file(filepath)
    os.remove(filepath)
    return messages


@cli.group()
def start() -> None:
    """Start a consumer"""


@cli.group()
def update() -> None:
    """Update a consumer"""


@start.command("ehr")
@click.option(
    "--rate",
    type=int,
    default=20,
    help="Rate at which EHR is requested from EMAP in queries per second",
)
def start_ehr_extraction(rate: int) -> None:
    """Start EHR extraction"""

    if rate == 0:
        raise RuntimeError("Cannot start EHR with extract rate of 0. Must be >0")

    _update_ehr_extract_rate(rate)


@update.command("ehr")
@click.option(
    "--rate",
    type=int,
    required=True,
    help="Rate at which EHR is requested from EMAP in queries per second",
)
def update_ehr_rate(rate: int) -> None:
    _update_ehr_extract_rate(rate)


def _update_ehr_extract_rate(rate: int) -> None:
    logger.info("Updating the EHR extraction rate")

    base_url = f"http://{config['ehr_api']['host']}:{config['ehr_api']['port']}"
    response = post(url=f"{base_url}/token-bucket-refresh-rate", json={"rate": rate})

    if response.status_code == 200:
        logger.info(
            "Successfully updated EHR extraction, with a "
            f"rate of {rate} queries/second"
        )

    else:
        raise RuntimeError(f"Failed to start EHR extraction: {response}")


@start.command("pacs")
@click.option(
    "--rate",
    type=int,
    default=5,
    help="Rate at which images are requested from PACS in images per second",
)
def start_pacs_extraction(rate: int) -> None:
    """Start PACS extraction"""
    raise NotImplementedError


@update.command("pacs")
@click.option(
    "--rate",
    type=int,
    required=True,
    help="Rate at which images are requested from PACS in images per second",
)
def update_pacs_rate(rate: int) -> None:
    raise NotImplementedError


@cli.command()
@click.option(
    "--queues",
    default="ehr,pacs",
    show_default=True,
    help="Comma seperated list of topics to consume messages from",
)
def stop(queues: str) -> None:
    """
    Stop extracting images and/or EHR data. Will consume all messages present on the
    topics and save them to a file
    """
    logger.info(f"Stopping extraction of {queues}")

    for topic in queues.split(","):
        logger.info(f"Consuming messages on {topic}")
        consume_all_messages_and_save_csv_file(topic)


# TODO: Replace by PIXL queue package
def create_connection() -> pika.BlockingConnection:

    params = pika.ConnectionParameters(
        host=config["rabbitmq"]["host"],
        port=int(config["rabbitmq"]["port"]),
        # credentials=
    )
    return pika.BlockingConnection(params)


def consume_all_messages_and_save_csv_file(
    queue_name: str, timeout_in_seconds: int = 5
) -> None:
    logger.info(
        f"Will consume all messages on {queue_name} queue and timeout after "
        f"{timeout_in_seconds} seconds"
    )

    # TODO: Replace by PIXL queue package
    connection = create_connection()
    channel = connection.channel()
    queue = channel.queue_declare(queue=queue_name)

    if queue.method.message_count > 0:
        logger.info("Found messages in the queue. Clearing the state file")
        clear_file(state_filepath_for_queue(queue_name))

    def callback(method: Any, properties: Any, body: Any) -> None:

        try:
            with open(state_filepath_for_queue(queue_name), "a") as csv_file:
                print(body.decode(), file=csv_file)
        except:  # noqa
            logger.debug("Failed to consume")

    generator = channel.consume(
        queue=queue_name,
        auto_ack=True,
        inactivity_timeout=timeout_in_seconds,  # Yields (None, None, None) after this
    )

    for args in generator:
        if all(arg is None for arg in args):
            logger.info("Stopping")
            break

        callback(*args)

    connection.close()


def state_filepath_for_queue(topic: str) -> Path:
    return Path(f"{topic.replace('/', '_')}.state")


class Messages(list):
    @classmethod
    def from_state_file(cls, filepath: Path) -> "Messages":
        logger.info(f"Creating messages from {filepath}")
        assert filepath.exists() and filepath.suffix == ".state"

        return cls(
            [
                line
                for line in open(filepath, "r").readlines()
                if string_is_non_empty(line)
            ]
        )

    def send(self, queue_name: str) -> None:
        logger.debug(f"Sending {len(self)} messages to topic {queue_name}")

        connection = create_connection()
        channel = connection.channel()
        channel.queue_declare(queue=queue_name)

        for message in self:
            channel.basic_publish(
                exchange="", routing_key=queue_name, body=message.encode("utf-8")
            )

        connection.close()
        logger.info(f"Sent {len(self)} messages")


def messages_from_csv(filepath: Path) -> Messages:

    expected_col_names = [
        "VAL_ID",
        "ACCESSION_NUMBER",
        "STUDY_INSTANCE_UID",
        "STUDY_DATE",
    ]
    logger.debug(
        f"Extracting messages from {filepath}. Expecting columns to include "
        f"{expected_col_names}"
    )

    df = pd.read_csv(filepath, header=0, dtype=str)  # First line is column names
    messages = Messages()

    if list(df.columns)[:4] != expected_col_names:
        raise ValueError(
            f"csv file expected to have at least {expected_col_names} as "
            f"column names"
        )

    mrn_col_name, acc_num_col_name, _, datetime_col_name = expected_col_names
    for _, row in df.iterrows():
        messages.append(
            f"{row[mrn_col_name]},"
            f"{row[acc_num_col_name]},"
            f"{row[datetime_col_name]}"
        )

    if len(messages) == 0:
        raise ValueError(f"Failed to find any messages in {filepath}")

    logger.debug(f"Created {len(messages)} messages from {filepath}")
    return messages


def queue_is_up() -> bool:
    connection = create_connection()
    connection_created_successfully = bool(connection.is_open)
    connection.close()
    return connection_created_successfully


def inform_user_that_queue_will_be_populated_from(path: Path) -> None:
    _ = input(
        f"Found a state file *{path}*. Please use --no-restart if this and other "
        f"state files should be ignored, or delete this file to ignore. Press "
        f"Ctrl-C to exit and any key to continue"
    )
