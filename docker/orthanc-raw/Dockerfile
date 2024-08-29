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

# Install requirements before copying modules
COPY ./pixl_core/pyproject.toml /pixl_core/pyproject.toml
COPY ./pixl_dcmd/pyproject.toml /pixl_dcmd/pyproject.toml

RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install pixl_core/ \
    && /.venv/bin/pip install pixl_dcmd/

COPY ./pixl_core/ /pixl_core
RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install --no-cache-dir --force-reinstall --no-deps ./pixl_core

COPY ./pixl_dcmd/ /pixl_dcmd
RUN --mount=type=cache,target=/root/.cache \
    /.venv/bin/pip install --no-cache-dir --force-reinstall --no-deps ./pixl_dcmd

COPY ./orthanc/orthanc-raw/plugin/pixl.py /etc/orthanc/pixl.py

# Orthanc can't substitute environment veriables as integers so copy and replace before running
ARG ORTHANC_RAW_MAXIMUM_STORAGE_SIZE
ARG ORTHANC_RAW_JOB_HISTORY_SIZE
ARG ORTHANC_CONCURRENT_JOBS
ARG ORTHANC_RAW_EXTRA_STABLE_SECONDS
ARG PIXL_DICOM_TRANSFER_TIMEOUT
COPY ./orthanc/orthanc-raw/config /run/secrets
RUN sed -i "s/\${ORTHANC_RAW_MAXIMUM_STORAGE_SIZE}/${ORTHANC_RAW_MAXIMUM_STORAGE_SIZE:-0}/g" /run/secrets/orthanc.json
RUN sed -i "s/\${ORTHANC_RAW_JOB_HISTORY_SIZE}/${ORTHANC_RAW_JOB_HISTORY_SIZE:-100}/g" /run/secrets/orthanc.json
RUN sed -i "s/\${ORTHANC_CONCURRENT_JOBS}/${ORTHANC_CONCURRENT_JOBS:-5}/g" /run/secrets/orthanc.json
RUN sed -i "s/\${ORTHANC_RAW_STABLE_SECONDS}/$((PIXL_DICOM_TRANSFER_TIMEOUT + ${ORTHANC_RAW_EXTRA_STABLE_SECONDS:-60}))/g" /run/secrets/orthanc.json

ENV PYTHONPATH=/.venv/lib64/python3.11/site-packages/
