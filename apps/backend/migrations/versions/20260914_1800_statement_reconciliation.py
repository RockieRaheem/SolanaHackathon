"""Add statement reconciliation records.

Revision ID: 20260914_1800
Revises: 20260914_1300
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_1800"
down_revision: str | None = "20260914_1300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "statement_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("file_name", sa.String(160), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="review", nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "statement_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Uuid(),
            sa.ForeignKey("statement_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("source_reference", sa.String(100), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default="unmatched", nullable=False),
        sa.Column("suggested_student_id", sa.Uuid(), sa.ForeignKey("students.id")),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), unique=True),
        sa.CheckConstraint("amount > 0", name="ck_statement_transactions_amount"),
        sa.UniqueConstraint("school_id", "source_reference"),
    )
    op.create_index(
        "ix_statement_transactions_review",
        "statement_transactions",
        ["school_id", "status", "transaction_date"],
    )
    for table in ("statement_imports", "statement_transactions"):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')


def downgrade() -> None:
    op.drop_table("statement_transactions")
    op.drop_table("statement_imports")
