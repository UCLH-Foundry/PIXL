#!/usr/bin/env bash
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

set -eux pipefail

THIS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PACKAGE_DIR="${THIS_DIR%/*}"
cd "$PACKAGE_DIR" || exit

pip install -r src/requirements.txt

CONF_FILE=../setup.cfg
mypy --config-file ${CONF_FILE} src/pixl_cli
isort --settings-path ${CONF_FILE} src/pixl_cli
black src/pixl_cli
flake8 --config ${CONF_FILE} src/pixl_cli

cd test/

docker compose up -d
# Wait until the queue is up and healthy
while ! docker ps | grep queue | grep -q healthy ;do
    sleep 40
done

pytest ../src/pixl_cli
docker compose down
