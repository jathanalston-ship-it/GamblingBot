"""trade plans + candidate analogs

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-24 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[Any]]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "trade_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        *_timestamps(),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("risk_per_share", sa.Float(), nullable=True),
        sa.Column("final_reward_risk", sa.Float(), nullable=True),
        sa.Column("expected_holding_days_low", sa.Integer(), nullable=True),
        sa.Column("expected_holding_days_high", sa.Integer(), nullable=True),
        sa.Column("suggested_shares", sa.Integer(), nullable=True),
        sa.Column("suggested_risk_dollars", sa.Float(), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_plans")),
        sa.UniqueConstraint("run_id", "symbol", name="uq_trade_plans_run_symbol"),
    )
    with op.batch_alter_table("trade_plans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_trade_plans_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_trade_plans_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_trade_plans_symbol"), ["symbol"], unique=False)
        batch_op.create_index(batch_op.f("ix_trade_plans_as_of"), ["as_of"], unique=False)

    op.create_table(
        "candidate_analogs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        *_timestamps(),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("regime", sa.String(length=16), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("avg_winner_r", sa.Float(), nullable=True),
        sa.Column("avg_loser_r", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_analogs")),
        sa.UniqueConstraint("run_id", "symbol", name="uq_candidate_analogs_run_symbol"),
    )
    with op.batch_alter_table("candidate_analogs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_candidate_analogs_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_candidate_analogs_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_candidate_analogs_symbol"), ["symbol"], unique=False)
        batch_op.create_index(batch_op.f("ix_candidate_analogs_as_of"), ["as_of"], unique=False)


def downgrade() -> None:
    op.drop_table("candidate_analogs")
    op.drop_table("trade_plans")
