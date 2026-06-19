"""instrument selections

Adds the ``instrument_selections`` table: one row per bullish thesis the
instrument-selection engine evaluated (chosen instrument, suggested structure,
candidate scoring).

Uses batch_alter_table so the migration is SQLite-safe.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_selections",
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("instrument", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("margin", sa.Float(), nullable=False),
        sa.Column("iv_rv_ratio", sa.Float(), nullable=True),
        sa.Column("expiry_days", sa.Integer(), nullable=True),
        sa.Column("long_strike", sa.Float(), nullable=True),
        sa.Column("short_strike", sa.Float(), nullable=True),
        sa.Column("target_delta", sa.Float(), nullable=True),
        sa.Column("contracts", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("est_cost", sa.Float(), nullable=True),
        sa.Column("max_loss", sa.Float(), nullable=True),
        sa.Column("max_profit", sa.Float(), nullable=True),
        sa.Column("rationale", sa.JSON(), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_instrument_selections_signal_id_signals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instrument_selections")),
    )
    with op.batch_alter_table("instrument_selections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_instrument_selections_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_instrument_selections_instrument"), ["instrument"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_instrument_selections_run_id"), ["run_id"], unique=False
        )
        batch_op.create_index(
            "ix_instrument_selections_run_instrument", ["run_id", "instrument"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_instrument_selections_signal_id"), ["signal_id"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_instrument_selections_symbol"), ["symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("instrument_selections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_instrument_selections_symbol"))
        batch_op.drop_index(batch_op.f("ix_instrument_selections_signal_id"))
        batch_op.drop_index("ix_instrument_selections_run_instrument")
        batch_op.drop_index(batch_op.f("ix_instrument_selections_run_id"))
        batch_op.drop_index(batch_op.f("ix_instrument_selections_instrument"))
        batch_op.drop_index(batch_op.f("ix_instrument_selections_created_at"))

    op.drop_table("instrument_selections")
