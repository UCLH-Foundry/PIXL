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
"""
replace_hashed_id_with_pseudo_study_uid
Revision ID: cb5ee12a6e20
Revises: bcaef54e2bfe
Create Date: 2024-05-01 20:31:31.670512

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cb5ee12a6e20"
down_revision: Union[str, None] = "bcaef54e2bfe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "image", sa.Column("pseudo_study_uid", sa.String(), nullable=True), schema="pipeline"
    )
    op.drop_column("image", "hashed_identifier", schema="pipeline")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "image",
        sa.Column("hashed_identifier", sa.VARCHAR(), autoincrement=False, nullable=True),
        schema="pipeline",
    )
    op.drop_column("image", "pseudo_study_uid", schema="pipeline")
    # ### end Alembic commands ###