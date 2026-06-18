"""trade intelligence columns

Enriches the ``trades`` table with the context needed for trade-intelligence
attribution: sector, denormalised regime label, entry reason and entry-bar
volume / relative volume. Also indexes ``exit_reason`` for slice queries.

Uses batch_alter_table so the migration is SQLite-safe.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sector", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("regime_label", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("entry_reason", sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column("entry_volume", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("entry_relative_volume", sa.Float(), nullable=True))
        batch_op.create_index(batch_op.f("ix_trades_sector"), ["sector"], unique=False)
        batch_op.create_index(batch_op.f("ix_trades_regime_label"), ["regime_label"], unique=False)
        batch_op.create_index(batch_op.f("ix_trades_entry_reason"), ["entry_reason"], unique=False)
        batch_op.create_index(batch_op.f("ix_trades_exit_reason"), ["exit_reason"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_trades_exit_reason"))
        batch_op.drop_index(batch_op.f("ix_trades_entry_reason"))
        batch_op.drop_index(batch_op.f("ix_trades_regime_label"))
        batch_op.drop_index(batch_op.f("ix_trades_sector"))
        batch_op.drop_column("entry_relative_volume")
        batch_op.drop_column("entry_volume")
        batch_op.drop_column("entry_reason")
        batch_op.drop_column("regime_label")
        batch_op.drop_column("sector")
