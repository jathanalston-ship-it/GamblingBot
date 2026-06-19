"""scan results

Adds the ``scan_results`` table: ranked momentum-scanner output, one row per
candidate per (run, date), with the full supporting feature set.

Index creation uses batch_alter_table so the migration is SQLite-safe.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_results",
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("momentum_score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("dollar_volume", sa.Float(), nullable=True),
        sa.Column("relative_volume", sa.Float(), nullable=True),
        sa.Column("distance_from_ath", sa.Float(), nullable=True),
        sa.Column("ema_fast", sa.Float(), nullable=True),
        sa.Column("ema_mid", sa.Float(), nullable=True),
        sa.Column("ema_slow", sa.Float(), nullable=True),
        sa.Column("atr", sa.Float(), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=True),
        sa.Column("sector_rs", sa.Float(), nullable=True),
        sa.Column("components", sa.JSON(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_results")),
        sa.UniqueConstraint("run_id", "as_of", "symbol", name="uq_scan_run_asof_symbol"),
    )
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scan_results_as_of"), ["as_of"], unique=False)
        batch_op.create_index("ix_scan_results_asof_rank", ["as_of", "rank"], unique=False)
        batch_op.create_index(
            "ix_scan_results_asof_score", ["as_of", "momentum_score"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_scan_results_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_scan_results_momentum_score"), ["momentum_score"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_scan_results_passed"), ["passed"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_results_rank"), ["rank"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_results_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_scan_results_run_rank", ["run_id", "rank"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_results_sector"), ["sector"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_results_symbol"), ["symbol"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("scan_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scan_results_symbol"))
        batch_op.drop_index(batch_op.f("ix_scan_results_sector"))
        batch_op.drop_index("ix_scan_results_run_rank")
        batch_op.drop_index(batch_op.f("ix_scan_results_run_id"))
        batch_op.drop_index(batch_op.f("ix_scan_results_rank"))
        batch_op.drop_index(batch_op.f("ix_scan_results_passed"))
        batch_op.drop_index(batch_op.f("ix_scan_results_momentum_score"))
        batch_op.drop_index(batch_op.f("ix_scan_results_created_at"))
        batch_op.drop_index("ix_scan_results_asof_score")
        batch_op.drop_index("ix_scan_results_asof_rank")
        batch_op.drop_index(batch_op.f("ix_scan_results_as_of"))

    op.drop_table("scan_results")
