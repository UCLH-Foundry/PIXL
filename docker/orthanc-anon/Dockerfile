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
FROM orthancteam/orthanc:24.7.3@sha256:57a3d037729897331027ddc00c12695b50f1effbbf805f855396f3d0248d2d5f
SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

# Create a virtual environment, recommended since python 3.11 and Debian bookworm based images
# where you get a warning when installing system-wide packages.
RUN export DEBIAN_FRONTEND=noninteractive && \
    apt-get update && \
    apt-get install --yes --no-install-recommends python3-venv tzdata
RUN python3 -m venv /.venv

# Install curl, used in system tests
RUN apt-get --assume-yes install curl

# Install requirements before copying modules
COPY ./pixl_core/pyproject.toml /pixl_core/pyproject.toml
COPY ./pixl_dcmd/pyproject.toml /pixl_dcmd/pyproject.toml

RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install pixl_core/ \
    && /.venv/bin/pip install pixl_dcmd/

COPY ./orthanc/orthanc-anon/plugin/pixl.py /etc/orthanc/pixl.py

COPY ./pixl_core/ /pixl_core
RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install --no-cache-dir --force-reinstall --no-deps ./pixl_core

COPY ./pixl_dcmd/ /pixl_dcmd
RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install --no-cache-dir --force-reinstall --no-deps ./pixl_dcmd

ARG ORTHANC_CONCURRENT_JOBS
COPY ./orthanc/orthanc-anon/config /run/secrets

RUN sed -i "s/\${ORTHANC_CONCURRENT_JOBS}/${ORTHANC_CONCURRENT_JOBS:-5}/g" /run/secrets/orthanc.json


ENV PYTHONPATH=/.venv/lib64/python3.11/site-packages/

