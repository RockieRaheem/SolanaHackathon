"""add controlled balance carry forward

Revision ID: e27d4c8a91b0
Revises: f13c9b2a4d60
Create Date: 2026-10-24 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e27d4c8a91b0"
down_revision: str | None = "f13c9b2a4d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "balance_carry_forwards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_close_id",
            sa.Uuid(),
            sa.ForeignKey("period_closes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "destination_period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("learner_count", sa.Integer(), nullable=False),
        sa.Column("debt_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("credit_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("posted_by", sa.String(120), nullable=False),
        sa.Column(
            "posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_close_id", name="uq_balance_carry_source_close"),
        sa.UniqueConstraint("source_period_id", name="uq_balance_carry_source_period"),
        sa.UniqueConstraint(
            "destination_period_id", name="uq_balance_carry_destination_period"
        ),
        sa.UniqueConstraint("school_id", "idempotency_key", name="uq_balance_carry_key"),
        sa.CheckConstraint("learner_count >= 0", name="ck_balance_carry_learner_count"),
        sa.CheckConstraint("debt_total >= 0", name="ck_balance_carry_debt_total"),
        sa.CheckConstraint("credit_total >= 0", name="ck_balance_carry_credit_total"),
        sa.CheckConstraint(
            "net_balance = debt_total - credit_total",
            name="ck_balance_carry_net_total",
        ),
        sa.CheckConstraint(
            "source_period_id <> destination_period_id",
            name="ck_balance_carry_distinct_periods",
        ),
    )
    op.create_index("ix_balance_carry_forwards_school_id", "balance_carry_forwards", ["school_id"])
    op.create_index(
        "ix_balance_carry_forwards_source_close_id",
        "balance_carry_forwards",
        ["source_close_id"],
    )
    op.create_index(
        "ix_balance_carry_forwards_source_period_id",
        "balance_carry_forwards",
        ["source_period_id"],
    )
    op.create_index(
        "ix_balance_carry_forwards_destination_period_id",
        "balance_carry_forwards",
        ["destination_period_id"],
    )
    op.create_index(
        "ix_balance_carry_school_posted",
        "balance_carry_forwards",
        ["school_id", "posted_at"],
    )

    op.create_table(
        "balance_carry_forward_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "carry_forward_id",
            sa.Uuid(),
            sa.ForeignKey("balance_carry_forwards.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "destination_period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_close_learner_id",
            sa.Uuid(),
            sa.ForeignKey("period_close_learners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ledger_entry_id",
            sa.Uuid(),
            sa.ForeignKey("ledger_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_name", sa.String(240), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint(
            "carry_forward_id", "student_id", name="uq_balance_carry_line_student"
        ),
        sa.UniqueConstraint(
            "destination_period_id",
            "student_id",
            name="uq_balance_carry_destination_student",
        ),
        sa.UniqueConstraint(
            "source_close_learner_id", name="uq_balance_carry_source_learner"
        ),
        sa.UniqueConstraint("ledger_entry_id", name="uq_balance_carry_ledger_entry"),
        sa.CheckConstraint("amount <> 0", name="ck_balance_carry_line_nonzero"),
    )
    for column in (
        "carry_forward_id",
        "school_id",
        "source_period_id",
        "destination_period_id",
        "source_close_learner_id",
        "student_id",
        "ledger_entry_id",
    ):
        op.create_index(
            f"ix_balance_carry_forward_lines_{column}",
            "balance_carry_forward_lines",
            [column],
        )
    op.create_index(
        "ix_balance_carry_lines_school_student",
        "balance_carry_forward_lines",
        ["school_id", "student_id"],
    )

    for table in ("balance_carry_forwards", "balance_carry_forward_lines"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY balance_carry_staff_read ON public.balance_carry_forwards
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY balance_carry_manager_insert ON public.balance_carry_forwards
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));
        CREATE POLICY balance_carry_lines_staff_read ON public.balance_carry_forward_lines
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY balance_carry_lines_manager_insert ON public.balance_carry_forward_lines
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));

        CREATE FUNCTION private.validate_balance_carry_batch()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.period_closes close_record
            JOIN public.academic_periods source_period
              ON source_period.id = close_record.period_id
            JOIN public.academic_periods destination_period
              ON destination_period.id = NEW.destination_period_id
            JOIN public.academic_years source_year
              ON source_year.id = source_period.academic_year_id
            JOIN public.academic_years destination_year
              ON destination_year.id = destination_period.academic_year_id
            WHERE close_record.id = NEW.source_close_id
              AND close_record.school_id = NEW.school_id
              AND close_record.period_id = NEW.source_period_id
              AND close_record.snapshot_hash = NEW.source_snapshot_hash
              AND source_period.school_id = NEW.school_id
              AND source_period.status = 'closed'
              AND destination_period.school_id = NEW.school_id
              AND destination_period.status IN ('draft','open')
              AND (destination_year.year, destination_period.sequence)
                    > (source_year.year, source_period.sequence)
              AND NOT EXISTS (
                SELECT 1
                FROM public.academic_periods candidate_period
                JOIN public.academic_years candidate_year
                  ON candidate_year.id = candidate_period.academic_year_id
                WHERE candidate_period.school_id = NEW.school_id
                  AND (candidate_year.year, candidate_period.sequence)
                        > (source_year.year, source_period.sequence)
                  AND (candidate_year.year, candidate_period.sequence)
                        < (destination_year.year, destination_period.sequence)
              )
          ) THEN
            RAISE EXCEPTION 'Balance carry periods or source snapshot are invalid'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_balance_carry_batch
        BEFORE INSERT ON public.balance_carry_forwards
        FOR EACH ROW EXECUTE FUNCTION private.validate_balance_carry_batch();

        CREATE FUNCTION private.validate_balance_carry_line()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.balance_carry_forwards carry
            JOIN public.period_close_learners source_line
              ON source_line.id = NEW.source_close_learner_id
            JOIN public.ledger_entries ledger
              ON ledger.id = NEW.ledger_entry_id
            WHERE carry.id = NEW.carry_forward_id
              AND carry.school_id = NEW.school_id
              AND carry.source_period_id = NEW.source_period_id
              AND carry.destination_period_id = NEW.destination_period_id
              AND source_line.period_close_id = carry.source_close_id
              AND source_line.student_id = NEW.student_id
              AND source_line.closing_balance = NEW.amount
              AND ledger.school_id = NEW.school_id
              AND ledger.period_id = NEW.destination_period_id
              AND ledger.student_id = NEW.student_id
              AND ledger.entry_type = 'carried_balance'
              AND ledger.amount = NEW.amount
          ) THEN
            RAISE EXCEPTION 'Balance carry learner or ledger evidence is inconsistent'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_balance_carry_line
        BEFORE INSERT ON public.balance_carry_forward_lines
        FOR EACH ROW EXECUTE FUNCTION private.validate_balance_carry_line();

        CREATE FUNCTION private.validate_balance_carry_totals()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE
          actual_count integer;
          actual_debt numeric(18,2);
          actual_credit numeric(18,2);
        BEGIN
          SELECT count(*),
                 coalesce(sum(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0),
                 coalesce(sum(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0)
            INTO actual_count, actual_debt, actual_credit
          FROM public.balance_carry_forward_lines
          WHERE carry_forward_id = NEW.id;
          IF actual_count <> NEW.learner_count
             OR actual_debt <> NEW.debt_total
             OR actual_credit <> NEW.credit_total THEN
            RAISE EXCEPTION 'Balance carry totals do not match learner evidence'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER validate_balance_carry_totals
        AFTER INSERT ON public.balance_carry_forwards
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION private.validate_balance_carry_totals();

        CREATE FUNCTION private.protect_balance_carry_evidence()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'Balance carry evidence is immutable';
        END $$;
        CREATE TRIGGER protect_balance_carry_batch
        BEFORE UPDATE OR DELETE ON public.balance_carry_forwards
        FOR EACH ROW EXECUTE FUNCTION private.protect_balance_carry_evidence();
        CREATE TRIGGER protect_balance_carry_line
        BEFORE UPDATE OR DELETE ON public.balance_carry_forward_lines
        FOR EACH ROW EXECUTE FUNCTION private.protect_balance_carry_evidence();

        CREATE FUNCTION private.protect_carried_balance_ledger()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.entry_type = 'carried_balance' THEN
            RAISE EXCEPTION 'Carried balance ledger evidence is immutable';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        CREATE TRIGGER protect_carried_balance_ledger
        BEFORE UPDATE OR DELETE ON public.ledger_entries
        FOR EACH ROW EXECUTE FUNCTION private.protect_carried_balance_ledger();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS protect_carried_balance_ledger ON public.ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS private.protect_carried_balance_ledger()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_balance_carry_totals ON public.balance_carry_forwards"
    )
    op.execute("DROP FUNCTION IF EXISTS private.validate_balance_carry_totals()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_balance_carry_line "
        "ON public.balance_carry_forward_lines"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS protect_balance_carry_batch ON public.balance_carry_forwards"
    )
    op.execute("DROP FUNCTION IF EXISTS private.protect_balance_carry_evidence()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_balance_carry_line "
        "ON public.balance_carry_forward_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS private.validate_balance_carry_line()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_balance_carry_batch ON public.balance_carry_forwards"
    )
    op.execute("DROP FUNCTION IF EXISTS private.validate_balance_carry_batch()")
    op.drop_table("balance_carry_forward_lines")
    op.drop_table("balance_carry_forwards")
