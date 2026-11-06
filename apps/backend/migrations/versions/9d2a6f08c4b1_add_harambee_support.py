"""Add privacy-preserving learner support campaigns.

Revision ID: 9d2a6f08c4b1
Revises: 189d96d367f9
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2a6f08c4b1"
down_revision: str | None = "189d96d367f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column(
            "requirement_assignment_id",
            sa.Uuid(),
            sa.ForeignKey("student_requirements.id"),
        ),
        sa.Column("public_code", sa.String(24), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("public_summary", sa.String(500), nullable=False),
        sa.Column("need_category", sa.String(40), nullable=False),
        sa.Column("target_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("risk_level", sa.String(16), server_default="review", nullable=False),
        sa.Column("risk_reasons", sa.Text(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("approved_by", sa.String(120)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("target_amount > 0", name="ck_support_cases_target_amount"),
        sa.CheckConstraint(
            "status in ('draft','review','published','funded','closed','withdrawn')",
            name="ck_support_cases_status",
        ),
    )
    op.create_index("ix_support_cases_school_status", "support_cases", ["school_id", "status"])
    op.create_index("ix_support_cases_student_period", "support_cases", ["student_id", "period_id"])
    op.create_index("ix_support_cases_period_id", "support_cases", ["period_id"])
    op.create_index(
        "ix_support_cases_requirement_assignment_id",
        "support_cases",
        ["requirement_assignment_id"],
    )

    op.create_table(
        "support_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id", sa.Uuid(), sa.ForeignKey("support_cases.id"), nullable=False, unique=True
        ),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column(
            "guardian_link_id", sa.Uuid(), sa.ForeignKey("guardian_links.id"), nullable=False
        ),
        sa.Column("method", sa.String(24), nullable=False),
        sa.Column("scope_version", sa.String(24), server_default="2026-10", nullable=False),
        sa.Column("anonymous_publication", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("gemma_processing", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "cross_border_processing", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "child_assent_status", sa.String(24), server_default="not_applicable", nullable=False
        ),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("recorded_by", sa.String(120), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('active','withdrawn')", name="ck_support_consents_status"),
    )
    op.create_index("ix_support_consents_school_id", "support_consents", ["school_id"])

    op.create_table(
        "support_ai_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("support_cases.id"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("model_name", sa.String(80), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="completed", nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_support_ai_reviews_case_time", "support_ai_reviews", ["case_id", "created_at"]
    )
    op.create_index("ix_support_ai_reviews_school_id", "support_ai_reviews", ["school_id"])

    op.create_table(
        "support_pledges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("support_cases.id"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("public_reference", sa.String(32), nullable=False, unique=True),
        sa.Column("external_reference", sa.String(100), nullable=False),
        sa.Column("donor_display_name", sa.String(100)),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by", sa.String(120)),
        sa.CheckConstraint("amount > 0", name="ck_support_pledges_amount"),
        sa.CheckConstraint(
            "status in ('pending','verified','rejected')", name="ck_support_pledges_status"
        ),
        sa.UniqueConstraint("case_id", "external_reference"),
    )
    op.create_index("ix_support_pledges_case_status", "support_pledges", ["case_id", "status"])
    op.create_index("ix_support_pledges_school_id", "support_pledges", ["school_id"])

    op.create_table(
        "support_attestations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("support_cases.id"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("attestation_type", sa.String(32), nullable=False),
        sa.Column("statement", sa.String(500), nullable=False),
        sa.Column("attendance_band", sa.String(24)),
        sa.Column("evidence_hash", sa.String(64)),
        sa.Column("is_public", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("verified_by", sa.String(120), nullable=False),
        sa.Column(
            "verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "attestation_type in ('guardian_acknowledgement','fulfilment',"
            "'enrolment','independent_audit')",
            name="ck_support_attestations_type",
        ),
    )
    op.create_index(
        "ix_support_attestations_case_time",
        "support_attestations",
        ["case_id", "verified_at"],
    )
    op.create_index("ix_support_attestations_school_id", "support_attestations", ["school_id"])

    read_roles = "ARRAY['owner','bursar','cashier','auditor']::text[]"
    write_roles = "ARRAY['owner','bursar']::text[]"
    tables = (
        "support_cases",
        "support_consents",
        "support_ai_reviews",
        "support_pledges",
        "support_attestations",
    )
    for table in tables:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_select ON public."{table}"
            FOR SELECT TO authenticated
            USING (private.has_school_role(school_id, {read_roles}))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write ON public."{table}"
            FOR ALL TO authenticated
            USING (private.has_school_role(school_id, {write_roles}))
            WITH CHECK (private.has_school_role(school_id, {write_roles}))
            """
        )
        op.execute(
            f'CREATE TRIGGER audit_{table}_insert AFTER INSERT ON public."{table}" '
            "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
        )
        op.execute(
            f'CREATE TRIGGER audit_{table}_update AFTER UPDATE ON public."{table}" '
            "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
        )

    op.execute(
        """
        CREATE FUNCTION private.protect_verified_support_pledge()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
            IF OLD.status = 'verified' THEN
                RAISE EXCEPTION 'Verified support contributions are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION private.protect_verified_support_pledge() "
        "FROM PUBLIC, anon, authenticated"
    )
    op.execute(
        """
        CREATE TRIGGER protect_verified_support_pledges
        BEFORE UPDATE OR DELETE ON public.support_pledges
        FOR EACH ROW EXECUTE FUNCTION private.protect_verified_support_pledge()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER protect_verified_support_pledges ON public.support_pledges")
    op.execute("DROP FUNCTION private.protect_verified_support_pledge()")
    tables = (
        "support_attestations",
        "support_pledges",
        "support_ai_reviews",
        "support_consents",
        "support_cases",
    )
    for table in tables:
        op.execute(f'DROP TRIGGER audit_{table}_update ON public."{table}"')
        op.execute(f'DROP TRIGGER audit_{table}_insert ON public."{table}"')
        op.drop_table(table)
