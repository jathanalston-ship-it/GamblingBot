"""market data provenance error reason

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-28 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("market_data_provenance", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error", sa.String(length=256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("market_data_provenance", schema=None) as batch_op:
        batch_op.drop_column("error")
