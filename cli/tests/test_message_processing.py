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

"""Test message processing module."""

import os
from collections.abc import Generator
from unittest.mock import Mock

import pytest
from _pytest.monkeypatch import MonkeyPatch
from core.patient_queue.producer import PixlProducer
from pixl_cli._message_processing import retry_until_export_count_is_unchanged


@pytest.fixture()
def _zero_message_count(monkeypatch: MonkeyPatch) -> None:
    """Ensure that message count is always zero, so that we don't have to deal with rabbitmq"""
    monkeypatch.setattr("pixl_cli._message_processing._message_count", lambda _: 0)


@pytest.fixture()
def mock_publisher(mocker) -> Generator[Mock, None, None]:
    """Patched publisher that does nothing, returns MagicMock of the publish method."""
    mocker.patch.object(PixlProducer, "__init__", return_value=None)
    mocker.patch.object(PixlProducer, "__enter__", return_value=PixlProducer)
    mocker.patch.object(PixlProducer, "__exit__")
    return mocker.patch.object(PixlProducer, "publish")


@pytest.mark.usefixtures("_zero_message_count")
def test_no_retry_if_none_exported(example_messages_df, db_session, mock_publisher):
    """
    GIVEN no images have been exported before starting, and num_retries set to 5
    WHEN rabbitmq messages set to zero and no messages are published to queue
    THEN populate_queue_and_db should never be called
    """
    os.environ["CLI_RETRY_SECONDS"] = "1"

    retry_until_export_count_is_unchanged(
        example_messages_df, num_retries=5, queues_to_populate=["imaging"]
    )

    mock_publisher.assert_not_called()


@pytest.mark.usefixtures("_zero_message_count")
def test_retry_with_image_exported_and_no_change(
    example_messages_df, rows_in_session, mock_publisher
):
    """
    GIVEN one image already has been exported, and num_retries set to 5
    WHEN rabbitmq messages set to zero and no messages are published to queue
    THEN populate_queue_and_db should be called once
    """
    os.environ["CLI_RETRY_SECONDS"] = "1"

    retry_until_export_count_is_unchanged(
        example_messages_df,
        num_retries=5,
        queues_to_populate=["imaging"],
    )

    mock_publisher.assert_called_once()


@pytest.mark.usefixtures("_zero_message_count")
def test_retry_with_image_exported_and_no_change_multiple_projects(
    example_messages_multiple_projects_df, rows_in_session, mock_publisher
):
    """
    GIVEN one image across two projects has been exported, and num_retries set to 5
    WHEN rabbitmq messages set to zero and no messages are published to queue
    THEN populate_queue_and_db should be called once
    """
    os.environ["CLI_RETRY_SECONDS"] = "1"

    retry_until_export_count_is_unchanged(
        example_messages_multiple_projects_df,
        num_retries=5,
        queues_to_populate=["imaging"],
    )

    mock_publisher.assert_called_once()
