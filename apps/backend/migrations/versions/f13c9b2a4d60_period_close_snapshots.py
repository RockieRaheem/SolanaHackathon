"""add immutable period close snapshots

Revision ID: f13c9b2a4d60
Revises: d54a9c7e210f
Create Date: 2026-10-24 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f13c9b2a4d60"
down_revision: str | None = "d54a9c7e210f"
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
        "period_closes",
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
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("learner_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        *_money_columns(),
        sa.Column("controls_json", sa.Text(), nullable=False),
        sa.Column("closed_by", sa.String(120), nullable=False),
        sa.Column(
            "closed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("period_id", name="uq_period_closes_period"),
        sa.UniqueConstraint("school_id", "idempotency_key", name="uq_period_closes_key"),
        sa.CheckConstraint("snapshot_version > 0", name="ck_period_closes_version"),
        sa.CheckConstraint("learner_count >= 0", name="ck_period_closes_learner_count"),
        sa.CheckConstraint("warning_count >= 0", name="ck_period_closes_warning_count"),
    )
    op.create_index("ix_period_closes_school_id", "period_closes", ["school_id"])
    op.create_index("ix_period_closes_period_id", "period_closes", ["period_id"])
    op.create_index("ix_period_closes_school_closed", "period_closes", ["school_id", "closed_at"])

    op.create_table(
        "period_close_learners",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "period_close_id",
            sa.Uuid(),
            sa.ForeignKey("period_closes.id", ondelete="RESTRICT"),
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
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id", ondelete="RESTRICT")),
        sa.Column("stream_id", sa.Uuid(), sa.ForeignKey("streams.id", ondelete="RESTRICT")),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_name", sa.String(240), nullable=False),
        sa.Column("class_name", sa.String(40), nullable=False),
        sa.Column("stream_name", sa.String(40)),
        *_money_columns(),
        sa.UniqueConstraint("period_close_id", "student_id", name="uq_period_close_learner"),
    )
    op.create_index(
        "ix_period_close_learners_period_close_id",
        "period_close_learners",
        ["period_close_id"],
    )
    op.create_index("ix_period_close_learners_school_id", "period_close_learners", ["school_id"])
    op.create_index("ix_period_close_learners_period_id", "period_close_learners", ["period_id"])
    op.create_index("ix_period_close_learners_student_id", "period_close_learners", ["student_id"])
    op.create_index(
        "ix_period_close_learners_school_student",
        "period_close_learners",
        ["school_id", "student_id"],
    )

    for table in ("period_closes", "period_close_learners"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY period_closes_staff_read ON public.period_closes
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY period_closes_manager_write ON public.period_closes
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));
        CREATE POLICY period_close_learners_staff_read ON public.period_close_learners
        FOR SELECT TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','auditor']::text[]));
        CREATE POLICY period_close_learners_manager_write ON public.period_close_learners
        FOR INSERT TO authenticated
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]));

        CREATE FUNCTION private.protect_period_close_snapshot()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'Period close snapshots are immutable';
        END $$;
        CREATE TRIGGER protect_period_close_snapshot
        BEFORE UPDATE OR DELETE ON public.period_closes
        FOR EACH ROW EXECUTE FUNCTION private.protect_period_close_snapshot();

        CREATE FUNCTION private.protect_period_close_learner_snapshot()
        RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'Learner close snapshots are immutable';
        END $$;
        CREATE TRIGGER protect_period_close_learner_snapshot
        BEFORE UPDATE OR DELETE ON public.period_close_learners
        FOR EACH ROW EXECUTE FUNCTION private.protect_period_close_learner_snapshot();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS protect_period_close_learner_snapshot "
        "ON public.period_close_learners"
    )
    op.execute("DROP FUNCTION IF EXISTS private.protect_period_close_learner_snapshot()")
    op.execute("DROP TRIGGER IF EXISTS protect_period_close_snapshot ON public.period_closes")
    op.execute("DROP FUNCTION IF EXISTS private.protect_period_close_snapshot()")
    op.drop_table("period_close_learners")
    op.drop_table("period_closes")
