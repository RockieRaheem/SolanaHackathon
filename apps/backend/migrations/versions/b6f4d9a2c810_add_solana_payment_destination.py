"""Add Solana destinations and provider-neutral settlement evidence.

Revision ID: b6f4d9a2c810
Revises: a72d5e8c19f4
Create Date: 2026-11-06 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6f4d9a2c810"
down_revision: str | None = "a72d5e8c19f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("stellar_anchors", "settlement_anchors")
    op.execute("UPDATE settlement_anchors SET network = 'offchain' WHERE network = 'testnet'")
    op.alter_column(
        "settlement_anchors",
        "network",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
        server_default="offchain",
    )
    op.alter_column(
        "settlement_anchors",
        "transaction_hash",
        new_column_name="transaction_signature",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
    op.alter_column(
        "settlement_anchors",
        "ledger_number",
        new_column_name="confirmation_slot",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    op.drop_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        "channel in ('schoolpay','bank','mobile_money','solana')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM support_payment_destinations WHERE channel = 'solana'")
    op.drop_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        "channel in ('schoolpay','bank','mobile_money')",
    )
    op.alter_column(
        "settlement_anchors",
        "confirmation_slot",
        new_column_name="ledger_number",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    op.execute(
        "UPDATE settlement_anchors SET transaction_signature = NULL, "
        "network = 'testnet' WHERE network = 'solana-devnet'"
    )
    op.alter_column(
        "settlement_anchors",
        "transaction_signature",
        new_column_name="transaction_hash",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "settlement_anchors",
        "network",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
        server_default="testnet",
    )
    op.rename_table("settlement_anchors", "stellar_anchors")
