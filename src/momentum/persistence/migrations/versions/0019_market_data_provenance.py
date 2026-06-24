"""market data provenance

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-24 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_data_provenance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bar_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bar_count", sa.Integer(), nullable=False),
        sa.Column("request_duration_ms", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_provenance")),
    )
    with op.batch_alter_table("market_data_provenance", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_market_data_provenance_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_market_data_provenance_symbol"), ["symbol"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_market_data_provenance_request_timestamp"),
            ["request_timestamp"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_market_data_provenance_run_id"), ["run_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("market_data_provenance")
