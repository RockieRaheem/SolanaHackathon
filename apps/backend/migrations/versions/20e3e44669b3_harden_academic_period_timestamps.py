"""harden academic period timestamps

Revision ID: 20e3e44669b3
Revises: c3b0e7686692
Create Date: 2026-10-11 10:06:05.924275
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20e3e44669b3"
down_revision: str | None = "c3b0e7686692"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("academic_years", "academic_periods"):
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    for table in ("academic_periods", "academic_years"):
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
