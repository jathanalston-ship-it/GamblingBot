"""scan results: strategy columns (trend average, breakout level/age, exit level)

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-11 02:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trend_ma", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("breakout_level", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("bars_since_breakout", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("exit_level", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.drop_column("exit_level")
        batch_op.drop_column("bars_since_breakout")
        batch_op.drop_column("breakout_level")
        batch_op.drop_column("trend_ma")
