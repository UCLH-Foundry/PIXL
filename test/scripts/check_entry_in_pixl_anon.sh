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

_sql_command="select * from emap_data.ehr_anon"
_result=$(docker exec system-test-postgres-1 /bin/bash -c \
  "PGPASSWORD=pixl_db_password psql -U pixl_db_username -d pixl -c \"$_sql_command\"")
echo "$_result" | grep -q "2 row"