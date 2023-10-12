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
import asyncio
import logging
import importlib.metadata

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from ._processing import process_message
from core.patient_queue.subscriber import PixlConsumer
from core.router import router, state


QUEUE_NAME = "pacs"

app = FastAPI(
    title="pacs-api",
    description="PACS extraction service",
    version=importlib.metadata.version("pixl_pacs"),
    default_response_class=JSONResponse,
)
app.include_router(router)

logger = logging.getLogger("uvicorn")


@app.on_event("startup")
async def startup_event() -> None:
    async with PixlConsumer(QUEUE_NAME, token_bucket=state.token_bucket) as consumer:
        asyncio.create_task(consumer.run(callback=process_message))
