"""scan implied vol + iv rank

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("implied_vol", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("iv_rank", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.drop_column("iv_rank")
        batch_op.drop_column("implied_vol")
