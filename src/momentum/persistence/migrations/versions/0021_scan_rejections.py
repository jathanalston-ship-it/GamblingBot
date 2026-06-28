"""scan rejections

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-28 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_rejections",
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
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_rejections")),
        sa.UniqueConstraint("run_id", "symbol", name="uq_scan_rejection_run_symbol"),
    )
    with op.batch_alter_table("scan_rejections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_scan_rejections_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_scan_rejections_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_rejections_symbol"), ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_table("scan_rejections")
