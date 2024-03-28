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
"""Testing utilities"""

from __future__ import annotations

import logging
import subprocess
from time import sleep
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def run_subprocess(
    cmd: list[str], working_dir: Optional[Path] = None, *, shell=False, timeout=360
) -> subprocess.CompletedProcess[bytes]:
    """
    Run a command but capture the stderr and stdout better than the CalledProcessError
    string representation does
    """
    logger.info("Running command %s", cmd)
    try:
        cp = subprocess.run(
            cmd,
            check=True,
            cwd=working_dir,
            shell=shell,  # noqa: S603 input is trusted
            timeout=timeout,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exception:
        logger.error("*** exception occurred running: '%s'", cmd)  # noqa: TRY400 will raise anyway
        logger.error("*** stdout:\n%s", exception.stdout.decode())  # noqa: TRY400
        logger.error("*** stderr:\n%s", exception.stderr.decode())  # noqa: TRY400
        raise
    else:
        logger.info("Success, returncode = %s", cp.returncode)
        logger.info("stdout =\n%s", cp.stdout.decode())
        logger.info("stderr =\n%s", cp.stderr.decode())
        return cp


def wait_for_condition(
    test_condition: Callable[..., bool],
    *,
    seconds_max: int = 1,
    seconds_interval: int = 1,
    seconds_condition_stays_true_for: Optional[int] = None,
    progress_string_fn: Optional[Callable[..., str]] = None,
) -> None:
    """
    Repeatedly test for a condition for the specified amount of time.
    :param test_condition: the condition to test for. The name of this method is used in
                            the logging output so recommended to name it well.
    :param seconds_max: maximum seconds to wait for condition to be true
    :param seconds_interval: time to sleep in between attempts
    :param seconds_condition_stays_true_for: if not None, check that the condition is still
                                             true this many seconds after first becoming true
    :param progress_string_fn: callable to generate a status string (eg. partial success) that
                              will be part of the log message at each attempt
    :raises AssertionError: if the condition doesn't occur during the specified period
    """
    for seconds in range(0, seconds_max, seconds_interval):
        success = test_condition()
        # must evaluate progress string *after* condition has been tested so it is most up to date
        progress_str = ": " + progress_string_fn() if progress_string_fn is not None else ""
        if success:
            logger.info("Achieved condition '%s' %s", test_condition.__name__, progress_str)
            if seconds_condition_stays_true_for is not None:
                # This is intended for the case where data may be dripping in and the correct
                # set of data may have been temporarily achieved, only to be joined by some
                # incorrect data. So we have the option to check it's stably true.
                logger.info(
                    "Checking that condition '%s' is still true in %s seconds",
                    test_condition.__name__,
                    seconds_condition_stays_true_for,
                )
                sleep(seconds_condition_stays_true_for)
                wait_for_condition(test_condition, progress_string_fn=progress_string_fn)
            return
        logger.info(
            "Waiting for condition '%s' (%s seconds out of %s) %s",
            test_condition.__name__,
            seconds,
            seconds_max,
            progress_str,
        )
        sleep(seconds_interval)
    err_str = (
        f"Condition {test_condition.__name__} was not achieved even after {seconds_max} seconds"
    )
    raise AssertionError(err_str)
