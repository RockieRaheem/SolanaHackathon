"""Create fee categories, line items, and installment rules.

Revision ID: 20260914_0900
Revises: 20260913_1900
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0900"
down_revision: str | None = "20260913_1900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fee_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("category_type", sa.String(30), server_default="other", nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_recurring", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("school_id", "code"),
    )
    op.create_table(
        "fee_structure_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "fee_structure_id",
            sa.Uuid(),
            sa.ForeignKey("fee_structures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("fee_categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_fee_structure_items_amount"),
        sa.UniqueConstraint("fee_structure_id", "category_id"),
    )
    op.create_table(
        "installment_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "fee_structure_id",
            sa.Uuid(),
            sa.ForeignKey("fee_structures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_installment_rules_amount"),
        sa.UniqueConstraint("fee_structure_id", "sort_order"),
    )
    for table in ("fee_categories", "fee_structure_items", "installment_rules"):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')


def downgrade() -> None:
    op.drop_table("installment_rules")
    op.drop_table("fee_structure_items")
    op.drop_table("fee_categories")
