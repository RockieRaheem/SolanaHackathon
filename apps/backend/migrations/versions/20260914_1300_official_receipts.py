"""Add durable official payment receipts.

Revision ID: 20260914_1300
Revises: 20260914_0900
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_1300"
down_revision: str | None = "20260914_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("receipt_no", sa.String(32), nullable=True))
    op.add_column("payments", sa.Column("payer_name", sa.String(160), nullable=True))
    op.add_column("payments", sa.Column("note", sa.String(240), nullable=True))
    op.execute(
        "UPDATE payments SET receipt_no = "
        "'H1-' || upper(substr(replace(id::text, '-', ''), 1, 12)) "
        "WHERE receipt_no IS NULL"
    )
    op.alter_column("payments", "receipt_no", nullable=False)
    op.create_unique_constraint("uq_payments_receipt_no", "payments", ["receipt_no"])


def downgrade() -> None:
    op.drop_constraint("uq_payments_receipt_no", "payments", type_="unique")
    op.drop_column("payments", "note")
    op.drop_column("payments", "payer_name")
    op.drop_column("payments", "receipt_no")
