"""research reports

Adds the ``research_reports`` table: the append-only audit trail of the
automated weekly research system (headline metrics + full JSON report + rendered
markdown). The reporting system is read-only; this table is its only output.

Uses batch_alter_table so the migration is SQLite-safe.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_reports",
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("num_trades", sa.Integer(), nullable=False),
        sa.Column("num_signals", sa.Integer(), nullable=False),
        sa.Column("num_regimes", sa.Integer(), nullable=False),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("net_pnl", sa.Float(), nullable=True),
        sa.Column("trend_capture", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_reports")),
        sa.UniqueConstraint("run_id", "period_end", name="uq_research_run_period"),
    )
    with op.batch_alter_table("research_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_research_reports_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_research_reports_period_end"), ["period_end"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_research_reports_period_start"), ["period_start"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_research_reports_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("research_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_research_reports_run_id"))
        batch_op.drop_index(batch_op.f("ix_research_reports_period_start"))
        batch_op.drop_index(batch_op.f("ix_research_reports_period_end"))
        batch_op.drop_index(batch_op.f("ix_research_reports_created_at"))

    op.drop_table("research_reports")
