#!/usr/bin/env bash

#
# Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

set -eo pipefail

BIN_DIR=$(cd $(dirname ${BASH_SOURCE[0]}) && pwd)
QUEUE_DIR="${BIN_DIR%/*}"
cd $QUEUE_DIR

CONF_FILE=../setup.cfg


mypy --config-file ${CONF_FILE} src/patient_queue

isort --settings-path ${CONF_FILE} src/patient_queue

black patient_queue

flake8 --config ${CONF_FILE}

ENV=test pytest src/patient_queue/tests
