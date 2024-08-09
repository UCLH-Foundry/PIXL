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
"""PIXL command line interface functionality"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import click
import requests
from core.exports import ParquetExport
from core.patient_queue.producer import PixlProducer
from decouple import RepositoryEnv, UndefinedValueError, config
from loguru import logger

from pixl_cli._config import SERVICE_SETTINGS, api_config_for_queue
from pixl_cli._database import exported_images_for_project
from pixl_cli._docker_commands import dc
from pixl_cli._io import (
    HOST_EXPORT_ROOT_DIR,
    make_radiology_linker_table,
    project_info,
    read_patient_info,
)
from pixl_cli._message_processing import (
    populate_queue_and_db,
    retry_until_export_count_is_unchanged,
)

# localhost needs to be added to the NO_PROXY environment variables on GAEs
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "localhost"

PIXL_ROOT = Path(__file__).parents[3].resolve()


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(*, debug: bool) -> None:
    """PIXL command line interface"""
    logging_level = "INFO" if not debug else "DEBUG"
    logger.remove()  # Remove all handlers
    logger.add(sys.stderr, level=logging_level)


cli.add_command(dc)


@cli.command()
@click.option(
    "--error",
    is_flag=True,
    show_default=True,
    default=False,
    help="Exit with error on missing env vars",
)
@click.option(
    "--sample-env-file",
    show_default=True,
    default=None,
    type=click.Path(exists=True),
    help="Path to the sample env file",
)
def check_env(*, error: bool, sample_env_file: Path) -> None:
    """Check that all variables from .env.sample are set either in .env or in environ"""
    if not sample_env_file:
        sample_env_file = PIXL_ROOT / ".env.sample"
    sample_config = RepositoryEnv(sample_env_file)
    for key in sample_config.data:
        try:
            config(key)
        except UndefinedValueError:
            logger.warning("Environment variable {} is not set", key)
            if error:
                raise


@cli.command()
@click.argument(
    "parquet-path", required=True, type=click.Path(path_type=Path, exists=True, file_okay=True)
)
@click.option(
    "--queues",
    default="imaging",
    show_default=True,
    help="Comma seperated list of queues to populate with messages generated from the "
    "input file(s)",
)
@click.option(
    "--start/--no-start",
    "start_processing",
    show_default=True,
    default=True,
    help="Start processing from the queues after population is complete",
)
@click.option(
    "--rate",
    type=float,
    default=None,
    help="Rate at which to process items from a queue (in items per second).",
)
@click.option(
    "--num-retries",
    "num_retries",
    type=int,
    show_default=True,
    default=5,
    help="Number of retries to attempt before giving up, 5 minute wait inbetween",
)
def populate(  # too many args
    parquet_path: Path,
    *,
    queues: str,
    rate: Optional[float],
    num_retries: int,
    start_processing: bool,
) -> None:
    """
    Populate a (set of) queue(s) from a parquet file directory
    PARQUET_DIR: Directory containing the public and private parquet input files and an
        extract_summary.json log file.
        It's expected that the directory structure will be:

            PARQUET-DIR
            ├── private
            │   ├── PERSON_LINKS.parquet
            │   └── PROCEDURE_OCCURRENCE_LINKS.parquet
            ├── public
            │   └── PROCEDURE_OCCURRENCE.parquet
            └── extract_summary.json
    """
    queues_to_populate = queues.split(",")
    if start_processing:
        _start_or_update_extract(queues=queues_to_populate, rate=rate)
    else:
        logger.info("Starting to process messages disabled, setting `--num-retries` to 0")
        num_retries = 0

    logger.info("Populating queue(s) {} from {}", queues_to_populate, parquet_path)
    messages_df = read_patient_info(parquet_path)

    populate_queue_and_db(queues_to_populate, messages_df)
    if num_retries != 0:
        retry_until_export_count_is_unchanged(messages_df, num_retries, queues_to_populate)


@cli.command()
@click.argument(
    "parquet-dir", required=True, type=click.Path(path_type=Path, exists=True, file_okay=False)
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Timeout to use for calling export API",
)
def export_patient_data(parquet_dir: Path, timeout: int) -> None:
    """
    Export processed radiology reports to parquet file.

    PARQUET_DIR: Directory containing the extract_summary.json log file
                 defining which extract to export patient data for.
    """
    project_name_raw, omop_es_datetime = project_info(parquet_dir)
    export = ParquetExport(project_name_raw, omop_es_datetime, HOST_EXPORT_ROOT_DIR)

    images = exported_images_for_project(export.project_slug)
    linker_data = make_radiology_linker_table(parquet_dir, images)
    export.export_radiology_linker(linker_data)

    # Call the Export API
    api_config = api_config_for_queue("export")
    response = requests.post(
        url=f"{api_config.base_url}/export-patient-data",
        json={"project_name": project_name_raw, "extract_datetime": omop_es_datetime.isoformat()},
        timeout=timeout,
    )

    success_code = 200
    if response.status_code != success_code:
        msg = (
            f"Failed to run export-patient-data due to: "
            f"error code {response.status_code} {response.text}"
        )
        raise RuntimeError(msg)


@cli.command()
@click.option(
    "--queues",
    default="imaging",
    show_default=True,
    help="Comma seperated list of queues to start consuming from",
)
@click.option(
    "--rate",
    type=float,
    default=None,
    help="Rate at which to process items from a queue (in items per second).",
)
def start(queues: str, rate: Optional[float]) -> None:
    """Start consumers for a set of queues"""
    if rate == 0:
        msg = "Cannot start extract with a rate of 0. Must be >0"
        raise RuntimeError(msg)

    _start_or_update_extract(queues=queues.split(","), rate=rate)


@cli.command()
@click.option(
    "--queues",
    default="imaging",
    show_default=True,
    help="Comma seperated list of queues to update the consume rate of",
)
@click.option(
    "--rate",
    type=float,
    required=True,
    help="Rate at which to process items from a queue (in items per second)",
)
def update(queues: str, rate: Optional[float]) -> None:
    """Update one or a list of consumers with a defined rate"""
    _start_or_update_extract(queues=queues.split(","), rate=rate)


def _start_or_update_extract(queues: list[str], rate: Optional[float]) -> None:
    """Start or update the rate of extraction for a list of queue names"""
    for queue in queues:
        _update_extract_rate(queue_name=queue, rate=rate)


def _update_extract_rate(queue_name: str, rate: Optional[float]) -> None:
    logger.info("Updating the extraction rate")

    api_config = api_config_for_queue(queue_name)

    if rate is None:
        if api_config.default_rate is None:
            msg = f"Cannot update the rate for {queue_name}. No valid rate was specified."
            raise ValueError(msg)
        rate = float(api_config.default_rate)
        logger.info("Using the default extract rate of {}/second", rate)

    logger.debug("POST {} to {}", rate, api_config.base_url)

    response = requests.post(
        url=f"{api_config.base_url}/token-bucket-refresh-rate",
        json={"rate": rate},
        timeout=10,
    )

    success_code = 200
    if response.status_code == success_code:
        logger.success("Updated {} extraction, with a rate of {} queries/second", queue_name, rate)

    else:
        msg = f"Failed to update rate on consumer for {queue_name}: {response}"
        raise RuntimeError(msg)


@cli.command()
@click.option(
    "--queues",
    default="imaging",
    show_default=True,
    help="Comma seperated list of queues to consume messages from",
)
@click.option(
    "--purge/--no-purge",
    show_default=True,
    default=False,
    help="Purge the queue after stopping the consumer",
)
def stop(queues: str, purge: bool) -> None:  # noqa: FBT001 bool argument
    """
    Stop extracting images by setting the rate to 0.
    In progress messages will continue to be processed.
    The queues retain their state and can be restarted unless the purge option is selected.
    """
    logger.info("Stopping extraction of {}", queues)

    for queue in queues.split(","):
        logger.info("Consuming messages on {}", queue)
        _update_extract_rate(queue_name=queue, rate=0)
        if purge:
            logger.info("Purging queue {}", queue)
            with PixlProducer(queue_name=queue, **SERVICE_SETTINGS["rabbitmq"]) as producer:
                producer.clear_queue()


@cli.command()
def kill() -> None:
    """Stop all the PIXL services"""
    os.system("docker compose stop")  # noqa: S605,S607


@cli.command()
@click.option(
    "--queues",
    default="imaging",
    show_default=True,
    help="Comma seperated list of queues to consume messages from",
)
def status(queues: str) -> None:
    """Get the status of the PIXL consumers"""
    for queue in queues.split(","):
        logger.info(f"[{queue:^10s}] refresh rate = ", _get_extract_rate(queue))


def _get_extract_rate(queue_name: str) -> str:
    """
    Get the extraction rate in items per second from a queue

    :param queue_name: Name of the queue to get the extract rate for (e.g. imaging)
    :return: The extract rate in items per seconds

    Throws a RuntimeError if the status code is not 200.
    """
    api_config = api_config_for_queue(queue_name)
    success_code = 200
    try:
        response = requests.get(url=f"{api_config.base_url}/token-bucket-refresh-rate", timeout=10)
        if response.status_code != success_code:
            msg = (f"Failed to get the extract rate for {queue_name} due to: {response.text}",)
            raise RuntimeError(msg)
        return str(json.loads(response.text)["rate"])

    except (ConnectionError, AssertionError):
        logger.error("Failed to get the extract rate for {}", queue_name)
        return "unknown"


def queue_is_up() -> Any:
    """Checks if the queue is up"""
    with PixlProducer(queue_name="") as producer:
        return producer.connection_open


def inform_user_that_queue_will_be_populated_from(path: Path) -> None:  # noqa: D103
    _ = input(
        f"Found a state file *{path}*. Please use --no-restart if this and other "
        f"state files should be ignored, or delete this file to ignore. Press "
        f"Ctrl-C to exit and any key to continue"
    )
