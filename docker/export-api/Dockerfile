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
FROM python:3.12.4-slim-bullseye@sha256:26ce493641ad3b1c8a6202117c31340c7bbb2dc126f1aeee8ea3972730a81dc6
SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

ARG TEST="false"

RUN export DEBIAN_FRONTEND=noninteractive && \
    apt-get update && \
    apt-get install --yes --no-install-recommends \
        procps \
        ca-certificates \
        iproute2 \
        libpq-dev \
        curl \
        gnupg \
        locales \
        tzdata

RUN sed -i '/en_GB.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
RUN  apt-get autoremove && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install requirements before copying modules
COPY ./pixl_core/pyproject.toml ./pixl_core/pyproject.toml
COPY ./pixl_export/pyproject.toml ./pixl_export/pyproject.toml
RUN pip3 install --no-cache-dir pixl_core/ \
    && pip3 install --no-cache-dir pixl_export/

COPY ./pixl_core/ pixl_core/
COPY ./pixl_export/ .
RUN pip install --no-cache-dir --force-reinstall --no-deps pixl_core/ \
    --no-cache-dir --force-reinstall --no-deps . && \
    if [ "$TEST" = "true" ]; then pip install --no-cache-dir pixl_core/[test] .[test]; fi

HEALTHCHECK CMD /usr/bin/curl -f http://0.0.0.0:8000/heart-beat || exit 1

ENTRYPOINT ["uvicorn", "pixl_export.main:app", "--host", "0.0.0.0", "--port", "8000"]
