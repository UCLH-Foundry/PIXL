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
FROM python:3.11.7-slim-bullseye

RUN export DEBIAN_FRONTEND=noninteractive && \
    apt-get update && \
    apt-get install --yes --no-install-recommends \
        procps \
        ca-certificates \
        iproute2 \
        curl \
        gnupg \
        locales

ARG PIXL_USER_UID
ARG PIXL_USER_GID
RUN groupadd --gid $PIXL_USER_GID pixl && useradd --uid $PIXL_USER_UID --gid $PIXL_USER_GID pixl
WORKDIR /app

COPY cogstack.py .
COPY pyproject.toml .

RUN --mount=type=cache,target=/root/.cache \
    pip install -e .

ENTRYPOINT ["uvicorn", "cogstack:app", "--host", "0.0.0.0", "--port", "8000"]
