"""add controlled period reopening

Revision ID: a72d5e8c19f4
Revises: c91b7e2a4f60
Create Date: 2026-10-25 10:00:00
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a72d5e8c19f4"
down_revision: str | None = "c91b7e2a4f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY_COLUMNS = (
    "opening_balance",
    "charges",
    "credits",
    "payments",
    "refunds",
    "reversals",
    "assessment_adjustments",
    "net_assessed",
    "net_collected",
    "period_activity",
    "closing_balance",
    "outstanding",
    "credit_balance",
)


def _money_columns() -> list[sa.Column]:
    return [sa.Column(name, sa.Numeric(18, 2), nullable=False) for name in MONEY_COLUMNS]


def upgrade() -> None:
    op.create_table(
        "period_reopenings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_close_id", sa.Uuid(), sa.ForeignKey("period_closes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("previous_reopening_id", sa.Uuid(), sa.ForeignKey("period_reopenings.id", ondelete="RESTRICT")),
        sa.Column("destination_period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id", ondelete="RESTRICT")),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("original_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("prior_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("revised_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("correction_count", sa.Integer(), nullable=False),
        sa.Column("learner_count", sa.Integer(), nullable=False),
        sa.Column("net_adjustment", sa.Numeric(18, 2), nullable=False),
        *_money_columns(),
        sa.Column("controls_json", sa.Text(), nullable=False),
        sa.Column("applied_by", sa.String(120), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_id", "idempotency_key", name="uq_period_reopenings_key"),
        sa.UniqueConstraint("period_id", "snapshot_version", name="uq_period_reopenings_version"),
        sa.CheckConstraint("snapshot_version > 1", name="ck_period_reopenings_version"),
        sa.CheckConstraint("correction_count > 0", name="ck_period_reopenings_corrections"),
        sa.CheckConstraint("learner_count >= 0", name="ck_period_reopenings_learners"),
    )
    op.create_index("ix_period_reopenings_school_id", "period_reopenings", ["school_id"])
    op.create_index("ix_period_reopenings_period_id", "period_reopenings", ["period_id"])
    op.create_index("ix_period_reopenings_original_close_id", "period_reopenings", ["original_close_id"])
    op.create_index("ix_period_reopenings_school_period", "period_reopenings", ["school_id", "period_id", "snapshot_version"])

    op.create_table(
        "period_reopening_corrections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reopening_id", sa.Uuid(), sa.ForeignKey("period_reopenings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("destination_period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id", ondelete="RESTRICT")),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("correction_type", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_name", sa.String(240), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False, unique=True),
        sa.UniqueConstraint("reopening_id", "student_id", name="uq_reopening_correction_student"),
        sa.CheckConstraint("correction_type in ('charge','credit')", name="ck_reopening_correction_type"),
        sa.CheckConstraint("amount <> 0", name="ck_reopening_correction_amount"),
        sa.CheckConstraint("(correction_type = 'charge' and amount > 0) or (correction_type = 'credit' and amount < 0)", name="ck_reopening_correction_sign"),
    )
    for column in ("reopening_id", "school_id", "period_id", "student_id"):
        op.create_index(f"ix_period_reopening_corrections_{column}", "period_reopening_corrections", [column])
    op.create_index("ix_reopening_corrections_school_student", "period_reopening_corrections", ["school_id", "student_id"])

    op.create_table(
        "period_reopening_learners",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reopening_id", sa.Uuid(), sa.ForeignKey("period_reopenings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id", ondelete="RESTRICT")),
        sa.Column("stream_id", sa.Uuid(), sa.ForeignKey("streams.id", ondelete="RESTRICT")),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_name", sa.String(240), nullable=False),
        sa.Column("class_name", sa.String(40), nullable=False),
        sa.Column("stream_name", sa.String(40)),
        *_money_columns(),
        sa.UniqueConstraint("reopening_id", "student_id", name="uq_reopening_learner"),
    )
    for column in ("reopening_id", "school_id", "period_id", "student_id"):
        op.create_index(f"ix_period_reopening_learners_{column}", "period_reopening_learners", [column])
    op.create_index("ix_reopening_learners_school_student", "period_reopening_learners", ["school_id", "student_id"])

    op.add_column("ledger_entries", sa.Column("reopening_correction_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_ledger_entries_reopening_correction_id",
        "ledger_entries",
        "period_reopening_corrections",
        ["reopening_correction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_ledger_entries_reopening_correction_id", "ledger_entries", ["reopening_correction_id"])

    for table in ("period_reopenings", "period_reopening_corrections", "period_reopening_learners"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY period_reopenings_staff_read ON public.period_reopenings
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY period_reopenings_owner_insert ON public.period_reopenings
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]));
        CREATE POLICY period_reopening_corrections_staff_read ON public.period_reopening_corrections
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY period_reopening_corrections_owner_insert ON public.period_reopening_corrections
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]));
        CREATE POLICY period_reopening_learners_staff_read ON public.period_reopening_learners
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY period_reopening_learners_owner_insert ON public.period_reopening_learners
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]));

        CREATE FUNCTION private.validate_period_reopening()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE prior_version integer; prior_hash text;
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.period_closes c
            JOIN public.academic_periods p ON p.id = c.period_id
            WHERE c.id = NEW.original_close_id AND c.school_id = NEW.school_id
              AND c.period_id = NEW.period_id AND c.snapshot_hash = NEW.original_snapshot_hash
              AND p.school_id = NEW.school_id AND p.status = 'closed'
          ) THEN
            RAISE EXCEPTION 'Controlled reopening source evidence is invalid' USING ERRCODE = '23514';
          END IF;
          SELECT snapshot_version, revised_snapshot_hash INTO prior_version, prior_hash
          FROM public.period_reopenings
          WHERE school_id = NEW.school_id AND period_id = NEW.period_id
          ORDER BY snapshot_version DESC LIMIT 1;
          IF prior_version IS NULL THEN
            IF NEW.snapshot_version <> 2 OR NEW.previous_reopening_id IS NOT NULL
               OR NEW.prior_snapshot_hash <> NEW.original_snapshot_hash THEN
              RAISE EXCEPTION 'First reopening revision is invalid' USING ERRCODE = '23514';
            END IF;
          ELSIF NEW.snapshot_version <> prior_version + 1
                OR NEW.prior_snapshot_hash <> prior_hash
                OR NOT EXISTS (
                  SELECT 1 FROM public.period_reopenings previous
                  WHERE previous.id = NEW.previous_reopening_id
                    AND previous.school_id = NEW.school_id
                    AND previous.period_id = NEW.period_id
                    AND previous.snapshot_version = prior_version
                ) THEN
            RAISE EXCEPTION 'Reopening revision chain is invalid' USING ERRCODE = '23514';
          END IF;
          IF NEW.destination_period_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.balance_carry_forwards carry
            JOIN public.academic_periods destination ON destination.id = carry.destination_period_id
            WHERE carry.school_id = NEW.school_id AND carry.source_period_id = NEW.period_id
              AND carry.destination_period_id = NEW.destination_period_id
              AND destination.status IN ('draft','open','closing')
          ) THEN
            RAISE EXCEPTION 'Reopening carry destination is invalid' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_period_reopening BEFORE INSERT ON public.period_reopenings
        FOR EACH ROW EXECUTE FUNCTION private.validate_period_reopening();

        CREATE FUNCTION private.validate_period_reopening_correction()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.period_reopenings reopening
            JOIN public.period_close_learners learner
              ON learner.period_close_id = reopening.original_close_id
            WHERE reopening.id = NEW.reopening_id AND reopening.school_id = NEW.school_id
              AND reopening.period_id = NEW.period_id
              AND reopening.destination_period_id IS NOT DISTINCT FROM NEW.destination_period_id
              AND learner.student_id = NEW.student_id
          ) THEN
            RAISE EXCEPTION 'Reopening correction is not tied to sealed learner evidence' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_period_reopening_correction
        BEFORE INSERT ON public.period_reopening_corrections
        FOR EACH ROW EXECUTE FUNCTION private.validate_period_reopening_correction();

        CREATE FUNCTION private.validate_reopening_ledger_entry()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NEW.reopening_correction_id IS NULL THEN RETURN NEW; END IF;
          IF NOT EXISTS (
            SELECT 1 FROM public.period_reopening_corrections correction
            WHERE correction.id = NEW.reopening_correction_id
              AND correction.school_id = NEW.school_id AND correction.student_id = NEW.student_id
              AND correction.amount = NEW.amount
              AND (
                (NEW.period_id = correction.period_id AND
                 ((correction.correction_type = 'charge' AND NEW.entry_type = 'period_correction_charge') OR
                  (correction.correction_type = 'credit' AND NEW.entry_type = 'period_correction_credit')))
                OR
                (NEW.period_id = correction.destination_period_id AND NEW.entry_type = 'carry_correction')
              )
          ) THEN
            RAISE EXCEPTION 'Controlled correction ledger evidence is inconsistent' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_reopening_ledger_entry BEFORE INSERT ON public.ledger_entries
        FOR EACH ROW EXECUTE FUNCTION private.validate_reopening_ledger_entry();

        CREATE FUNCTION private.validate_period_reopening_totals()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE correction_rows integer; learner_rows integer; source_ledgers integer;
                destination_ledgers integer; adjustment numeric(18,2);
        BEGIN
          SELECT count(*), coalesce(sum(amount), 0) INTO correction_rows, adjustment
          FROM public.period_reopening_corrections WHERE reopening_id = NEW.id;
          SELECT count(*) INTO learner_rows FROM public.period_reopening_learners WHERE reopening_id = NEW.id;
          SELECT count(*) INTO source_ledgers FROM public.ledger_entries ledger
          JOIN public.period_reopening_corrections correction
            ON correction.id = ledger.reopening_correction_id
          WHERE correction.reopening_id = NEW.id AND ledger.period_id = NEW.period_id;
          SELECT count(*) INTO destination_ledgers FROM public.ledger_entries ledger
          JOIN public.period_reopening_corrections correction
            ON correction.id = ledger.reopening_correction_id
          WHERE correction.reopening_id = NEW.id AND ledger.period_id = NEW.destination_period_id;
          IF correction_rows <> NEW.correction_count OR learner_rows <> NEW.learner_count
             OR adjustment <> NEW.net_adjustment OR source_ledgers <> NEW.correction_count
             OR (NEW.destination_period_id IS NOT NULL AND destination_ledgers <> NEW.correction_count)
             OR (NEW.destination_period_id IS NULL AND destination_ledgers <> 0) THEN
            RAISE EXCEPTION 'Controlled reopening totals do not match immutable evidence' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER validate_period_reopening_totals
        AFTER INSERT ON public.period_reopenings DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION private.validate_period_reopening_totals();

        CREATE FUNCTION private.protect_period_reopening_evidence()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN RAISE EXCEPTION 'Controlled reopening evidence is immutable'; END $$;
        CREATE TRIGGER protect_period_reopenings BEFORE UPDATE OR DELETE ON public.period_reopenings
        FOR EACH ROW EXECUTE FUNCTION private.protect_period_reopening_evidence();
        CREATE TRIGGER protect_period_reopening_corrections BEFORE UPDATE OR DELETE ON public.period_reopening_corrections
        FOR EACH ROW EXECUTE FUNCTION private.protect_period_reopening_evidence();
        CREATE TRIGGER protect_period_reopening_learners BEFORE UPDATE OR DELETE ON public.period_reopening_learners
        FOR EACH ROW EXECUTE FUNCTION private.protect_period_reopening_evidence();

        CREATE OR REPLACE FUNCTION private.reject_closed_period_mutation()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        DECLARE target_period uuid; controlled boolean := false;
        BEGIN
          target_period := CASE WHEN TG_OP = 'DELETE' THEN OLD.period_id ELSE NEW.period_id END;
          IF TG_TABLE_NAME = 'ledger_entries' AND TG_OP = 'INSERT'
             AND NEW.reopening_correction_id IS NOT NULL THEN
            SELECT EXISTS (
              SELECT 1 FROM public.period_reopening_corrections correction
              WHERE correction.id = NEW.reopening_correction_id
                AND correction.school_id = NEW.school_id
                AND correction.student_id = NEW.student_id
                AND target_period IN (correction.period_id, correction.destination_period_id)
            ) INTO controlled;
          END IF;
          IF NOT controlled AND EXISTS (
            SELECT 1 FROM public.academic_periods WHERE id = target_period AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'This academic period is closed and cannot be changed' USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.period_id <> NEW.period_id AND EXISTS (
            SELECT 1 FROM public.academic_periods WHERE id = OLD.period_id AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'Records cannot be moved out of a closed academic period' USING ERRCODE = '23514';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        REVOKE ALL ON FUNCTION private.reject_closed_period_mutation() FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS validate_reopening_ledger_entry ON public.ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS private.validate_reopening_ledger_entry()")
    op.execute("DROP TRIGGER IF EXISTS protect_period_reopening_learners ON public.period_reopening_learners")
    op.execute("DROP TRIGGER IF EXISTS protect_period_reopening_corrections ON public.period_reopening_corrections")
    op.execute("DROP TRIGGER IF EXISTS protect_period_reopenings ON public.period_reopenings")
    op.execute("DROP FUNCTION IF EXISTS private.protect_period_reopening_evidence()")
    op.execute("DROP TRIGGER IF EXISTS validate_period_reopening_totals ON public.period_reopenings")
    op.execute("DROP FUNCTION IF EXISTS private.validate_period_reopening_totals()")
    op.execute("DROP TRIGGER IF EXISTS validate_period_reopening_correction ON public.period_reopening_corrections")
    op.execute("DROP FUNCTION IF EXISTS private.validate_period_reopening_correction()")
    op.execute("DROP TRIGGER IF EXISTS validate_period_reopening ON public.period_reopenings")
    op.execute("DROP FUNCTION IF EXISTS private.validate_period_reopening()")
    op.drop_index("ix_ledger_entries_reopening_correction_id", table_name="ledger_entries")
    op.drop_constraint("fk_ledger_entries_reopening_correction_id", "ledger_entries", type_="foreignkey")
    op.drop_column("ledger_entries", "reopening_correction_id")
    op.drop_table("period_reopening_learners")
    op.drop_table("period_reopening_corrections")
    op.drop_table("period_reopenings")
