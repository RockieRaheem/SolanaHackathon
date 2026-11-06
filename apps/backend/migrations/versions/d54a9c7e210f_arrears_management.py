"""complete arrears management workflow

Revision ID: d54a9c7e210f
Revises: c83d7a2f14e6
Create Date: 2026-10-23 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d54a9c7e210f"
down_revision: str | None = "c83d7a2f14e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arrears_follow_ups",
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
        sa.Column("contact_method", sa.String(20), nullable=False),
        sa.Column("contacted_person", sa.String(120), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column("next_action", sa.String(240)),
        sa.Column("next_action_date", sa.Date()),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("school_id", "idempotency_key", name="uq_arrears_followup_key"),
        sa.CheckConstraint(
            "contact_method in ('call','in_person','email','sms','whatsapp','letter','other')",
            name="ck_arrears_followups_method",
        ),
        sa.CheckConstraint(
            "outcome in ('contacted','no_answer','commitment','dispute','statement_sent','other')",
            name="ck_arrears_followups_outcome",
        ),
    )
    op.create_index("ix_arrears_follow_ups_school_id", "arrears_follow_ups", ["school_id"])
    op.create_index("ix_arrears_follow_ups_period_id", "arrears_follow_ups", ["period_id"])
    op.create_index("ix_arrears_follow_ups_student_id", "arrears_follow_ups", ["student_id"])
    op.create_index(
        "ix_arrears_followups_account",
        "arrears_follow_ups",
        ["school_id", "period_id", "student_id", "created_at"],
    )
    op.create_index(
        "ix_arrears_followups_next_action", "arrears_follow_ups", ["school_id", "next_action_date"]
    )

    op.create_table(
        "arrears_payment_promises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "follow_up_id",
            sa.Uuid(),
            sa.ForeignKey("arrears_follow_ups.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("promised_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("paid_at_creation", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("cancellation_reason", sa.String(500)),
        sa.Column("cancelled_by", sa.String(120)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("follow_up_id", name="uq_arrears_promise_followup"),
        sa.CheckConstraint("promised_amount > 0", name="ck_arrears_promises_amount"),
        sa.CheckConstraint("paid_at_creation >= 0", name="ck_arrears_promises_paid_baseline"),
        sa.CheckConstraint("status in ('active','cancelled')", name="ck_arrears_promises_status"),
    )
    op.create_index(
        "ix_arrears_payment_promises_school_id", "arrears_payment_promises", ["school_id"]
    )
    op.create_index(
        "ix_arrears_payment_promises_period_id", "arrears_payment_promises", ["period_id"]
    )
    op.create_index(
        "ix_arrears_payment_promises_student_id", "arrears_payment_promises", ["student_id"]
    )
    op.create_index(
        "ix_arrears_promises_account",
        "arrears_payment_promises",
        ["school_id", "period_id", "student_id", "due_date"],
    )

    for table in ("arrears_follow_ups", "arrears_payment_promises"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY arrears_followups_staff_access ON public.arrears_follow_ups
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY arrears_followups_manager_access ON public.arrears_follow_ups
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));
        CREATE POLICY arrears_promises_staff_access ON public.arrears_payment_promises
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY arrears_promises_manager_access ON public.arrears_payment_promises
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));

        CREATE FUNCTION private.protect_arrears_followup_evidence()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'Arrears follow-up evidence is immutable';
        END $$;
        CREATE TRIGGER protect_arrears_followup_evidence
        BEFORE UPDATE OR DELETE ON public.arrears_follow_ups
        FOR EACH ROW EXECUTE FUNCTION private.protect_arrears_followup_evidence();

        CREATE FUNCTION private.protect_arrears_promise_evidence()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Payment promise evidence cannot be deleted';
          END IF;
          IF NEW.follow_up_id <> OLD.follow_up_id OR NEW.school_id <> OLD.school_id
             OR NEW.period_id <> OLD.period_id OR NEW.student_id <> OLD.student_id
             OR NEW.promised_amount <> OLD.promised_amount
             OR NEW.paid_at_creation <> OLD.paid_at_creation OR NEW.due_date <> OLD.due_date
             OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'Payment promise source evidence is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER protect_arrears_promise_evidence
        BEFORE UPDATE OR DELETE ON public.arrears_payment_promises
        FOR EACH ROW EXECUTE FUNCTION private.protect_arrears_promise_evidence();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS protect_arrears_promise_evidence ON public.arrears_payment_promises"
    )
    op.execute("DROP FUNCTION IF EXISTS private.protect_arrears_promise_evidence()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_arrears_followup_evidence ON public.arrears_follow_ups"
    )
    op.execute("DROP FUNCTION IF EXISTS private.protect_arrears_followup_evidence()")
    op.drop_table("arrears_payment_promises")
    op.drop_table("arrears_follow_ups")
