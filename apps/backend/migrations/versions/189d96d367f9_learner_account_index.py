"""learner_account_index

Revision ID: 189d96d367f9
Revises: 81d7c62772c3
Create Date: 2026-10-15 23:05:20.837897
"""

from collections.abc import Sequence

from alembic import op

revision: str = "189d96d367f9"
down_revision: str | None = "81d7c62772c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ledger_entries_student_created",
        "ledger_entries",
        ["student_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_student_created", table_name="ledger_entries")
