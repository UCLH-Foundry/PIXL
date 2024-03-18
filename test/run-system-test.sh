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
cd "${PACKAGE_DIR}/test"

setup() {
    docker compose --env-file .env -p system-test down --volumes
    #
    # Note: cannot run as single docker compose command due to different build contexts
    docker compose --env-file .env -p system-test up --wait -d --build --remove-orphans
    # Warning: Requires to be run from the project root
    (
    	cd "${PACKAGE_DIR}"
    	docker compose --env-file test/.env --env-file .secrets.env -p system-test up --wait -d --build
    )

    ./scripts/insert_test_data.sh
}

teardown() {
    (
    	cd "${PACKAGE_DIR}"
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
    setup

    # These two variables are needed for creating the pixl user and group on the GHA runner.
    # Don't worry about passing them into pytest if you're running pytest manually or through your
    # IDE - they're only used inside an "if GITHUB_ACTIONS" block anyway.
    # We could do this in the setup function, but we don't at that point know the location of the
    # exports dir (how the exports dir is determined is due to change anyway)
    source .env
    export PIXL_USER_UID PIXL_USER_GID
    pytest --verbose --log-cli-level INFO

    echo FINISHED PYTEST COMMAND
    teardown
    echo SYSTEM TEST SUCCESSFUL
fi
