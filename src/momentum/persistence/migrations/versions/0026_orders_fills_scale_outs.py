"""orders + fills tables; trades scale-out / current-stop columns

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fills",
        sa.Column("order_id", sa.String(length=96), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fees", sa.Float(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fills")),
    )
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_fills_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_fills_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_fills_symbol"), ["symbol"], unique=False)
        batch_op.create_index("ix_fills_symbol_ts", ["symbol", "ts"], unique=False)
        batch_op.create_index(batch_op.f("ix_fills_ts"), ["ts"], unique=False)

    op.create_table(
        "orders",
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.String(length=96), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("time_in_force", sa.String(length=8), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("avg_fill_price", sa.Float(), nullable=True),
        sa.Column("total_fees", sa.Float(), nullable=False),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column("created_ts", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("order_id", name=op.f("uq_orders_order_id")),
    )
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_orders_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_created_ts"), ["created_ts"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_orders_run_symbol", ["run_id", "symbol"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_symbol"), ["symbol"], unique=False)

    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_stop", sa.Float(), nullable=True))
        # server_default backfills existing rows; models own the Python default.
        batch_op.add_column(
            sa.Column("scaled_out_quantity", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("scaled_out_pnl", sa.Float(), nullable=False, server_default="0.0")
        )


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_column("scaled_out_pnl")
        batch_op.drop_column("scaled_out_quantity")
        batch_op.drop_column("current_stop")

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_symbol"))
        batch_op.drop_index(batch_op.f("ix_orders_status"))
        batch_op.drop_index("ix_orders_run_symbol")
        batch_op.drop_index(batch_op.f("ix_orders_run_id"))
        batch_op.drop_index(batch_op.f("ix_orders_created_ts"))
        batch_op.drop_index(batch_op.f("ix_orders_created_at"))

    op.drop_table("orders")
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fills_ts"))
        batch_op.drop_index("ix_fills_symbol_ts")
        batch_op.drop_index(batch_op.f("ix_fills_symbol"))
        batch_op.drop_index(batch_op.f("ix_fills_order_id"))
        batch_op.drop_index(batch_op.f("ix_fills_created_at"))

    op.drop_table("fills")
