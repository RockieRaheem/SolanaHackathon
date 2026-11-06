"""add support referrals and consent

Revision ID: e30afe762c9b
Revises: a5da2b77f0d5
Create Date: 2026-10-16 14:26:47.779752
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e30afe762c9b"
down_revision: str | None = "a5da2b77f0d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_referrals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "guardian_link_id",
            sa.Uuid(),
            sa.ForeignKey("guardian_links.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("outstanding_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("overdue_since", sa.Date(), nullable=False),
        sa.Column("days_overdue_snapshot", sa.Integer(), nullable=False),
        sa.Column("priority_band", sa.String(16), nullable=False),
        sa.Column("priority_reasons", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), server_default="awaiting_consent", nullable=False),
        sa.Column("privacy_notice_version", sa.String(24)),
        sa.Column(
            "guardian_authority_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("age_verification_method", sa.String(32)),
        sa.Column("anonymous_publication", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("gemma_processing", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "cross_border_processing", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("child_assent_status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("child_assent_reason", sa.String(240)),
        sa.Column("consented_by_user_id", sa.Uuid()),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("student_id", "period_id", name="uq_support_referrals_student_period"),
        sa.CheckConstraint(
            "status in ('awaiting_consent','consented','declined','withdrawn','case_submitted')",
            name="ck_support_referrals_status",
        ),
        sa.CheckConstraint(
            "child_assent_status in "
            "('pending','agreed','declined','not_applicable','unable_to_express')",
            name="ck_support_referrals_assent",
        ),
    )
    op.create_index(
        "ix_support_referrals_school_status", "support_referrals", ["school_id", "status"]
    )
    for column in ("school_id", "period_id", "student_id", "guardian_link_id"):
        op.create_index(f"ix_support_referrals_{column}", "support_referrals", [column])
    op.execute('ALTER TABLE public."support_referrals" ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public."support_referrals" FROM anon, authenticated')
    op.execute("""
        CREATE POLICY support_referrals_school_select ON public.support_referrals
        FOR SELECT TO authenticated
        USING (private.has_school_role(
            school_id, ARRAY['owner','bursar','auditor']::text[]
        ))
    """)
    op.execute("""
        CREATE POLICY support_referrals_school_write ON public.support_referrals
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        WITH CHECK (private.has_school_role(
            school_id, ARRAY['owner','bursar']::text[]
        ))
    """)
    op.execute(
        "CREATE TRIGGER audit_support_referrals_insert AFTER INSERT ON "
        "public.support_referrals FOR EACH ROW EXECUTE FUNCTION "
        "public.capture_audit_event()"
    )
    op.execute(
        "CREATE TRIGGER audit_support_referrals_update AFTER UPDATE ON "
        "public.support_referrals FOR EACH ROW EXECUTE FUNCTION "
        "public.capture_audit_event()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_support_referrals_update ON public.support_referrals")
    op.execute("DROP TRIGGER audit_support_referrals_insert ON public.support_referrals")
    op.drop_table("support_referrals")
