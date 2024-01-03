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

"""Interaction with PIXL database"""
from typing import Optional

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Date, DateTime


class Base(DeclarativeBase):
    """sqlalchemy base class"""


class Extract(Base):
    """extract table"""

    __tablename__ = "extract"

    extract_id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str]


class Image(Base):
    """image table"""

    __tablename__ = "image"

    image_id: Mapped[int] = mapped_column(primary_key=True)
    accession_number: Mapped[str]
    study_date: Mapped[Date] = mapped_column(Date())
    mrn: Mapped[str]
    hashed_identifier: Mapped[Optional[str]]
    exported_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    extract: Mapped["Extract"] = relationship()
    extract_id: Mapped[int] = mapped_column(ForeignKey("extract.extract_id"))
