"""add controlled learner rollover

Revision ID: c91b7e2a4f60
Revises: e27d4c8a91b0
Create Date: 2026-10-24 23:15:00
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91b7e2a4f60"
down_revision: str | None = "e27d4c8a91b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learner_rollovers",
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
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("placed_count", sa.Integer(), nullable=False),
        sa.Column("held_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("departed_count", sa.Integer(), nullable=False),
        sa.Column("applied_by", sa.String(120), nullable=False),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_close_id", name="uq_learner_rollovers_source_close"),
        sa.UniqueConstraint("source_period_id", name="uq_learner_rollovers_source_period"),
        sa.UniqueConstraint(
            "destination_period_id", name="uq_learner_rollovers_destination_period"
        ),
        sa.UniqueConstraint("school_id", "idempotency_key", name="uq_learner_rollovers_key"),
        sa.CheckConstraint("candidate_count >= 0", name="ck_learner_rollovers_candidates"),
        sa.CheckConstraint(
            "placed_count + held_count + completed_count + departed_count = candidate_count",
            name="ck_learner_rollovers_decision_totals",
        ),
        sa.CheckConstraint(
            "source_period_id <> destination_period_id",
            name="ck_learner_rollovers_distinct_periods",
        ),
    )
    for column in ("school_id", "source_close_id", "source_period_id", "destination_period_id"):
        op.create_index(f"ix_learner_rollovers_{column}", "learner_rollovers", [column])
    op.create_index(
        "ix_learner_rollovers_school_applied", "learner_rollovers", ["school_id", "applied_at"]
    )

    op.create_table(
        "learner_rollover_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rollover_id",
            sa.Uuid(),
            sa.ForeignKey("learner_rollovers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
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
        sa.Column("enrollment_id", sa.Uuid(), sa.ForeignKey("enrollments.id", ondelete="RESTRICT")),
        sa.Column(
            "source_class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id", ondelete="RESTRICT")
        ),
        sa.Column("source_stream_id", sa.Uuid(), sa.ForeignKey("streams.id", ondelete="RESTRICT")),
        sa.Column(
            "target_class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id", ondelete="RESTRICT")
        ),
        sa.Column("target_stream_id", sa.Uuid(), sa.ForeignKey("streams.id", ondelete="RESTRICT")),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_name", sa.String(240), nullable=False),
        sa.Column("source_class_name", sa.String(80), nullable=False),
        sa.Column("source_stream_name", sa.String(80)),
        sa.Column("target_class_name", sa.String(80)),
        sa.Column("target_stream_name", sa.String(80)),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(240)),
        sa.Column("previous_status", sa.String(20), nullable=False),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.UniqueConstraint("rollover_id", "student_id", name="uq_rollover_lines_student"),
        sa.UniqueConstraint("source_close_learner_id", name="uq_rollover_lines_source_learner"),
        sa.UniqueConstraint("enrollment_id", name="uq_rollover_lines_enrollment"),
        sa.CheckConstraint(
            "decision in ('continue','promote','repeat','hold','complete','depart')",
            name="ck_rollover_lines_decision",
        ),
        sa.CheckConstraint(
            "(decision in ('continue','promote','repeat','hold') and new_status = 'active') or (decision = 'complete' and new_status = 'completed') or (decision = 'depart' and new_status = 'withdrawn')",
            name="ck_rollover_lines_result",
        ),
    )
    for column in (
        "rollover_id",
        "school_id",
        "source_close_learner_id",
        "student_id",
        "enrollment_id",
    ):
        op.create_index(f"ix_learner_rollover_lines_{column}", "learner_rollover_lines", [column])
    op.create_index(
        "ix_rollover_lines_school_student", "learner_rollover_lines", ["school_id", "student_id"]
    )

    for table in ("learner_rollovers", "learner_rollover_lines"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY learner_rollovers_staff_read ON public.learner_rollovers
        FOR SELECT TO authenticated USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY learner_rollovers_manager_insert ON public.learner_rollovers
        FOR INSERT TO authenticated WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));
        CREATE POLICY learner_rollover_lines_staff_read ON public.learner_rollover_lines
        FOR SELECT TO authenticated USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY learner_rollover_lines_manager_insert ON public.learner_rollover_lines
        FOR INSERT TO authenticated WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));

        CREATE FUNCTION private.validate_learner_rollover_batch()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.period_closes close_record
            JOIN public.academic_periods source_period ON source_period.id = close_record.period_id
            JOIN public.academic_periods destination_period ON destination_period.id = NEW.destination_period_id
            JOIN public.academic_years source_year ON source_year.id = source_period.academic_year_id
            JOIN public.academic_years destination_year ON destination_year.id = destination_period.academic_year_id
            JOIN public.balance_carry_forwards carry ON carry.source_period_id = source_period.id AND carry.destination_period_id = destination_period.id
            WHERE close_record.id = NEW.source_close_id
              AND close_record.school_id = NEW.school_id
              AND close_record.period_id = NEW.source_period_id
              AND close_record.snapshot_hash = NEW.source_snapshot_hash
              AND source_period.school_id = NEW.school_id AND source_period.status = 'closed'
              AND destination_period.school_id = NEW.school_id AND destination_period.status IN ('draft','open')
              AND (destination_year.year, destination_period.sequence) > (source_year.year, source_period.sequence)
              AND NOT EXISTS (
                SELECT 1 FROM public.academic_periods candidate_period
                JOIN public.academic_years candidate_year ON candidate_year.id = candidate_period.academic_year_id
                WHERE candidate_period.school_id = NEW.school_id
                  AND (candidate_year.year, candidate_period.sequence) > (source_year.year, source_period.sequence)
                  AND (candidate_year.year, candidate_period.sequence) < (destination_year.year, destination_period.sequence)
              )
          ) THEN RAISE EXCEPTION 'Learner rollover periods or source evidence are invalid' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_learner_rollover_batch BEFORE INSERT ON public.learner_rollovers
        FOR EACH ROW EXECUTE FUNCTION private.validate_learner_rollover_batch();

        CREATE FUNCTION private.validate_learner_rollover_line()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.learner_rollovers rollover
            JOIN public.period_close_learners source_line ON source_line.id = NEW.source_close_learner_id
            JOIN public.students student ON student.id = NEW.student_id
            WHERE rollover.id = NEW.rollover_id AND rollover.school_id = NEW.school_id
              AND source_line.period_close_id = rollover.source_close_id
              AND source_line.student_id = NEW.student_id
              AND source_line.class_id IS NOT DISTINCT FROM NEW.source_class_id
              AND source_line.stream_id IS NOT DISTINCT FROM NEW.source_stream_id
              AND student.school_id = NEW.school_id AND student.status = NEW.new_status
          ) THEN RAISE EXCEPTION 'Learner rollover source evidence is inconsistent' USING ERRCODE = '23514';
          END IF;
          IF NEW.decision IN ('continue','promote','repeat') AND NEW.target_class_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.enrollments enrollment
            JOIN public.learner_rollovers rollover ON rollover.id = NEW.rollover_id
            WHERE enrollment.id = NEW.enrollment_id AND enrollment.student_id = NEW.student_id
              AND enrollment.period_id = rollover.destination_period_id
              AND enrollment.class_id = NEW.target_class_id
              AND enrollment.stream_id IS NOT DISTINCT FROM NEW.target_stream_id
          ) THEN RAISE EXCEPTION 'Learner rollover destination placement is inconsistent' USING ERRCODE = '23514';
          END IF;
          IF NEW.decision IN ('hold','complete','depart') AND (NEW.enrollment_id IS NOT NULL OR NEW.target_class_id IS NOT NULL OR NEW.target_stream_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Non-placement rollover decision has a placement' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER validate_learner_rollover_line BEFORE INSERT ON public.learner_rollover_lines
        FOR EACH ROW EXECUTE FUNCTION private.validate_learner_rollover_line();

        CREATE FUNCTION private.validate_learner_rollover_totals()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE actual_total integer; actual_placed integer; actual_held integer; actual_completed integer; actual_departed integer;
        BEGIN
          SELECT count(*), count(*) FILTER (WHERE decision IN ('continue','promote','repeat')),
                 count(*) FILTER (WHERE decision = 'hold'), count(*) FILTER (WHERE decision = 'complete'),
                 count(*) FILTER (WHERE decision = 'depart')
          INTO actual_total, actual_placed, actual_held, actual_completed, actual_departed
          FROM public.learner_rollover_lines WHERE rollover_id = NEW.id;
          IF (actual_total, actual_placed, actual_held, actual_completed, actual_departed)
             <> (NEW.candidate_count, NEW.placed_count, NEW.held_count, NEW.completed_count, NEW.departed_count) THEN
            RAISE EXCEPTION 'Learner rollover totals do not match decision evidence' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER validate_learner_rollover_totals AFTER INSERT OR UPDATE ON public.learner_rollovers
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION private.validate_learner_rollover_totals();

        CREATE FUNCTION private.protect_learner_rollover_evidence()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN RAISE EXCEPTION 'Learner rollover evidence is immutable'; END $$;
        CREATE TRIGGER protect_learner_rollover_batch BEFORE UPDATE OR DELETE ON public.learner_rollovers
        FOR EACH ROW EXECUTE FUNCTION private.protect_learner_rollover_evidence();
        CREATE TRIGGER protect_learner_rollover_line BEFORE UPDATE OR DELETE ON public.learner_rollover_lines
        FOR EACH ROW EXECUTE FUNCTION private.protect_learner_rollover_evidence();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS protect_learner_rollover_line ON public.learner_rollover_lines"
    )
    op.execute("DROP TRIGGER IF EXISTS protect_learner_rollover_batch ON public.learner_rollovers")
    op.execute("DROP FUNCTION IF EXISTS private.protect_learner_rollover_evidence()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_learner_rollover_totals ON public.learner_rollovers"
    )
    op.execute("DROP FUNCTION IF EXISTS private.validate_learner_rollover_totals()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_learner_rollover_line ON public.learner_rollover_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS private.validate_learner_rollover_line()")
    op.execute("DROP TRIGGER IF EXISTS validate_learner_rollover_batch ON public.learner_rollovers")
    op.execute("DROP FUNCTION IF EXISTS private.validate_learner_rollover_batch()")
    op.drop_table("learner_rollover_lines")
    op.drop_table("learner_rollovers")
