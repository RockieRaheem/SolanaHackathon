"""Create fee, payment, ledger, and Stellar anchor records.

Revision ID: 20260913_1900
Revises: 20260913_1700
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_1900"
down_revision: str | None = "20260913_1700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fee_structures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("school_id", "class_id", "academic_year", "term"),
    )
    op.create_table(
        "student_fee_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fee_structure_id", sa.Uuid(), sa.ForeignKey("fee_structures.id"), nullable=False
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("student_id", "fee_structure_id"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("external_reference", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("status", sa.String(24), server_default="reconciled", nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("school_id", "external_reference"),
    )
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "payment_id",
            sa.Uuid(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "stellar_anchors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), unique=True, nullable=False
        ),
        sa.Column("commitment_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("network", sa.String(20), server_default="testnet", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("transaction_hash", sa.String(64)),
        sa.Column("ledger_number", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for table in (
        "fee_structures",
        "student_fee_assignments",
        "payments",
        "payment_allocations",
        "ledger_entries",
        "stellar_anchors",
    ):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')


def downgrade() -> None:
    for table in (
        "stellar_anchors",
        "ledger_entries",
        "payment_allocations",
        "payments",
        "student_fee_assignments",
        "fee_structures",
    ):
        op.drop_table(table)
