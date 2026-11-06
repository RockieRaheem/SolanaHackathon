"""add guardian-authored support case workflow

Revision ID: f42c8e910ab7
Revises: e30afe762c9b
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f42c8e910ab7"
down_revision: str | None = "e30afe762c9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "support_cases",
        sa.Column(
            "referral_id",
            sa.Uuid(),
            sa.ForeignKey("support_referrals.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column("support_cases", sa.Column("guardian_auth_user_id", sa.Uuid()))
    op.add_column("support_cases", sa.Column("private_context", sa.Text()))
    op.add_column("support_cases", sa.Column("review_notes", sa.String(500)))
    op.add_column("support_cases", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("support_cases", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_support_cases_referral_id", "support_cases", ["referral_id"], unique=True)
    op.create_index(
        "ix_support_cases_guardian_auth_user_id", "support_cases", ["guardian_auth_user_id"]
    )
    op.drop_constraint("ck_support_cases_status", "support_cases", type_="check")
    op.create_check_constraint(
        "ck_support_cases_status",
        "support_cases",
        "status in ('draft','changes_requested','submitted','review','approved',"
        "'published','funded','closed','withdrawn')",
    )
    op.create_index(
        "uq_support_cases_active_general_obligation",
        "support_cases",
        ["student_id", "period_id"],
        unique=True,
        postgresql_where=sa.text(
            "requirement_assignment_id IS NULL AND status NOT IN ('closed','withdrawn')"
        ),
    )
    op.create_index(
        "uq_support_cases_active_requirement",
        "support_cases",
        ["requirement_assignment_id"],
        unique=True,
        postgresql_where=sa.text(
            "requirement_assignment_id IS NOT NULL AND status NOT IN ('closed','withdrawn')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_support_cases_active_requirement", table_name="support_cases")
    op.drop_index("uq_support_cases_active_general_obligation", table_name="support_cases")
    op.drop_constraint("ck_support_cases_status", "support_cases", type_="check")
    op.create_check_constraint(
        "ck_support_cases_status",
        "support_cases",
        "status in ('draft','review','published','funded','closed','withdrawn')",
    )
    op.drop_index("ix_support_cases_guardian_auth_user_id", table_name="support_cases")
    op.drop_index("ix_support_cases_referral_id", table_name="support_cases")
    op.drop_column("support_cases", "reviewed_at")
    op.drop_column("support_cases", "submitted_at")
    op.drop_column("support_cases", "review_notes")
    op.drop_column("support_cases", "private_context")
    op.drop_column("support_cases", "guardian_auth_user_id")
    op.drop_column("support_cases", "referral_id")
