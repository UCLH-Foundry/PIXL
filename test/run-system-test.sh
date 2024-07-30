#!/bin/bash
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
set -euxo pipefail
BIN_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PACKAGE_DIR="${BIN_DIR%/*}"
EXPORTS_DIR="${PACKAGE_DIR}/projects/exports"
cd "${PACKAGE_DIR}/test"

setup() {
    # NOTE: the `pixl dc` command only work when run from the PIXL project root.
    # However, doing so will fail unless a valid .env file with all the necessary environment 
    # variables is present.
    docker compose --env-file .env -p system-test down --volumes

    # Note: cannot run as single docker compose command due to different build contexts
    docker compose --env-file .env -p system-test up --wait -d --build --remove-orphans
    # Warning: Requires to be run from the project root
    (
      cd "${PACKAGE_DIR}"
      docker compose --env-file test/.env --env-file test/.secrets.env -p system-test up --wait -d --build
    )
}

teardown() {
    (
      cd "${PACKAGE_DIR}"
      rm -r "${EXPORTS_DIR}/test-extract-uclh-omop-cdm-dicomweb/"
      rm -r "${EXPORTS_DIR}/test-extract-uclh-omop-cdm/"
      docker compose -f docker-compose.yml -f test/docker-compose.yml -p system-test down --volumes
    )
}

# Allow user to perform just setup so that pytest may be run repeatedly without
# redoing the setup again and again. This means that pytest must now be responsible
# for clearing up anything it creates (export temp dir?)
subcmd=${1:-""}

if [ "$subcmd" = "setup" ]; then
    setup
elif [ "$subcmd" = "teardown" ]; then
    teardown
else
    # setup flags used for pytest
    declare -a PYTEST_FLAGS

    # Add individual options to the array
    PYTEST_FLAGS+=("--verbose")
    PYTEST_FLAGS+=("--log-cli-level" "INFO")
    if [ "$subcmd" = "coverage" ]; then
        PYTEST_FLAGS+=("--cov" "--cov-report=xml")
    fi
    # Run the tests
    setup
    pytest "${PYTEST_FLAGS[@]}"
    echo FINISHED PYTEST COMMAND
    teardown
    echo SYSTEM TEST SUCCESSFUL
fi
