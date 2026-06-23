"""conviction explanation

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-23 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conviction_scores") as batch_op:
        batch_op.add_column(sa.Column("explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conviction_scores") as batch_op:
        batch_op.drop_column("explanation")
