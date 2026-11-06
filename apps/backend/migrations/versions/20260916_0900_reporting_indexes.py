"""Add reporting query indexes.

Revision ID: 20260916_0900
Revises: 20260914_1800
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0900"
down_revision: str | None = "20260914_1800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_payments_school_received", "payments", ["school_id", "received_at"])
    op.create_index("ix_payment_allocations_payment", "payment_allocations", ["payment_id"])
    op.create_index("ix_student_fee_assignments_student", "student_fee_assignments", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_student_fee_assignments_student", table_name="student_fee_assignments")
    op.drop_index("ix_payment_allocations_payment", table_name="payment_allocations")
    op.drop_index("ix_payments_school_received", table_name="payments")
