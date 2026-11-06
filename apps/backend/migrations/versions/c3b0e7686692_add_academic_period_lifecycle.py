"""add academic period lifecycle

Revision ID: c3b0e7686692
Revises: 5342e3f4519b
Create Date: 2026-10-11 08:59:35.049907
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3b0e7686692"
down_revision: str | None = "5342e3f4519b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "academic_years",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("start_date <= end_date", name="ck_academic_years_date_order"),
        sa.CheckConstraint(
            "status in ('draft', 'open', 'closing', 'closed')",
            name="ck_academic_years_status",
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "name", name="uq_academic_years_school_name"),
        sa.UniqueConstraint("school_id", "year", name="uq_academic_years_school_year"),
    )
    op.create_index("ix_academic_years_school_id", "academic_years", ["school_id"])
    op.create_table(
        "academic_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("academic_year_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=False),
        sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("sequence > 0", name="ck_periods_positive_sequence"),
        sa.CheckConstraint(
            "opening_date <= due_date and due_date <= closing_date",
            name="ck_periods_date_order",
        ),
        sa.CheckConstraint(
            "status in ('draft', 'open', 'closing', 'closed')",
            name="ck_periods_status",
        ),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academic_year_id", "name", name="uq_periods_year_name"),
        sa.UniqueConstraint("academic_year_id", "sequence", name="uq_periods_year_sequence"),
    )
    op.create_index(
        "ix_academic_periods_academic_year_id", "academic_periods", ["academic_year_id"]
    )
    op.create_index(
        "ix_academic_periods_school_dates",
        "academic_periods",
        ["school_id", "opening_date", "closing_date"],
    )
    op.create_index("ix_academic_periods_school_id", "academic_periods", ["school_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_academic_periods_one_operational_per_school
        ON academic_periods (school_id)
        WHERE status IN ('open', 'closing')
        """
    )

    for table in ("enrollments", "fee_structures", "requirements", "payments"):
        op.add_column(table, sa.Column("period_id", sa.Uuid(), nullable=True))

    op.execute(
        """
        WITH candidates AS (
            SELECT s.school_id, e.academic_year AS year
            FROM enrollments e JOIN students s ON s.id = e.student_id
            UNION SELECT school_id, academic_year FROM fee_structures
            UNION SELECT school_id, academic_year FROM requirements
            UNION SELECT school_id, EXTRACT(YEAR FROM received_at)::integer FROM payments
        )
        INSERT INTO academic_years (id, school_id, name, year, start_date, end_date, status)
        SELECT gen_random_uuid(), school_id, year::text || ' Academic Year', year,
               make_date(year, 1, 1), make_date(year, 12, 31), 'draft'
        FROM candidates GROUP BY school_id, year
        """
    )
    op.execute(
        """
        WITH candidates AS (
            SELECT s.school_id, e.academic_year AS year, e.term AS sequence
            FROM enrollments e JOIN students s ON s.id = e.student_id
            UNION SELECT school_id, academic_year, term FROM fee_structures
            UNION SELECT school_id, academic_year, term FROM requirements
            UNION SELECT school_id, EXTRACT(YEAR FROM received_at)::integer, 1 FROM payments
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY school_id ORDER BY year DESC, sequence DESC
            ) AS recency
            FROM (SELECT DISTINCT school_id, year, sequence FROM candidates) distinct_periods
        )
        INSERT INTO academic_periods (
            id, academic_year_id, school_id, name, sequence,
            opening_date, closing_date, due_date, status
        )
        SELECT gen_random_uuid(), ay.id, ranked.school_id,
               'Term ' || ranked.sequence, ranked.sequence,
               make_date(
                 ranked.year,
                 CASE ranked.sequence WHEN 1 THEN 1 WHEN 2 THEN 5 ELSE 9 END,
                 1
               ),
               (make_date(
                  ranked.year,
                  CASE ranked.sequence WHEN 1 THEN 5 WHEN 2 THEN 9 ELSE 12 END,
                  1
                ) + CASE WHEN ranked.sequence = 3
                         THEN interval '30 days' ELSE interval '-1 day' END)::date,
               make_date(
                 ranked.year,
                 CASE ranked.sequence WHEN 1 THEN 2 WHEN 2 THEN 6 ELSE 10 END,
                 1
               ),
               CASE WHEN ranked.recency = 1 THEN 'open' ELSE 'closed' END
        FROM ranked JOIN academic_years ay
          ON ay.school_id = ranked.school_id AND ay.year = ranked.year
        """
    )
    op.execute(
        """
        UPDATE academic_years ay SET status = state.status
        FROM (
            SELECT academic_year_id,
                   CASE WHEN bool_or(status = 'open') THEN 'open' ELSE 'closed' END AS status
            FROM academic_periods GROUP BY academic_year_id
        ) state WHERE state.academic_year_id = ay.id
        """
    )
    op.execute(
        """
        UPDATE enrollments e SET period_id = ap.id
        FROM students s, academic_years ay, academic_periods ap
        WHERE s.id = e.student_id AND ay.school_id = s.school_id
          AND ay.year = e.academic_year AND ap.academic_year_id = ay.id
          AND ap.sequence = e.term
        """
    )
    for table in ("fee_structures", "requirements"):
        op.execute(
            f"""
            UPDATE {table} item SET period_id = ap.id
            FROM academic_years ay, academic_periods ap
            WHERE ay.school_id = item.school_id AND ay.year = item.academic_year
              AND ap.academic_year_id = ay.id AND ap.sequence = item.term
            """
        )
    op.execute(
        """
        UPDATE payments p SET period_id = COALESCE(
            (SELECT e.period_id FROM payment_allocations pa
             JOIN enrollments e ON e.student_id = pa.student_id
             JOIN academic_periods ap ON ap.id = e.period_id
             JOIN academic_years ay ON ay.id = ap.academic_year_id
             WHERE pa.payment_id = p.id
               AND ay.year = EXTRACT(YEAR FROM p.received_at)::integer
             ORDER BY ay.year DESC, ap.sequence DESC LIMIT 1),
            (SELECT ap.id FROM academic_periods ap
             JOIN academic_years ay ON ay.id = ap.academic_year_id
             WHERE ap.school_id = p.school_id
               AND ay.year = EXTRACT(YEAR FROM p.received_at)::integer
             ORDER BY ap.sequence DESC LIMIT 1)
        )
        """
    )
    for table in ("enrollments", "fee_structures", "requirements", "payments"):
        op.alter_column(table, "period_id", nullable=False)
        op.create_index(f"ix_{table}_period_id", table, ["period_id"])
        op.create_foreign_key(
            f"fk_{table}_period_id_academic_periods",
            table,
            "academic_periods",
            ["period_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute("ALTER TABLE academic_years ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE academic_periods ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON academic_years, academic_periods FROM anon, authenticated")
    for table in ("academic_years", "academic_periods"):
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_select ON {table} FOR SELECT TO authenticated
            USING (private.has_school_role(
                school_id, ARRAY['owner', 'bursar', 'cashier', 'auditor']::text[]
            ))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write ON {table} FOR ALL TO authenticated
            USING (private.has_school_role(school_id, ARRAY['owner', 'bursar']::text[]))
            WITH CHECK (private.has_school_role(school_id, ARRAY['owner', 'bursar']::text[]))
            """
        )

    op.execute(
        """
        CREATE FUNCTION private.reject_closed_period_mutation()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        DECLARE target_period uuid;
        BEGIN
          target_period := CASE WHEN TG_OP = 'DELETE' THEN OLD.period_id ELSE NEW.period_id END;
          IF EXISTS (
            SELECT 1 FROM public.academic_periods
            WHERE id = target_period AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'This academic period is closed and cannot be changed'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.period_id <> NEW.period_id AND EXISTS (
            SELECT 1 FROM public.academic_periods
            WHERE id = OLD.period_id AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'Records cannot be moved out of a closed academic period'
              USING ERRCODE = '23514';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION private.reject_closed_period_mutation() FROM PUBLIC")
    for table in ("enrollments", "fee_structures", "requirements", "payments"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_closed_period
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION private.reject_closed_period_mutation()
            """
        )


def downgrade() -> None:
    for table in ("enrollments", "fee_structures", "requirements", "payments"):
        op.execute(f"DROP TRIGGER {table}_reject_closed_period ON {table}")
    op.execute("DROP FUNCTION private.reject_closed_period_mutation()")
    for table in ("enrollments", "fee_structures", "requirements", "payments"):
        op.drop_constraint(f"fk_{table}_period_id_academic_periods", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_period_id", table_name=table)
        op.drop_column(table, "period_id")
    op.drop_table("academic_periods")
    op.drop_table("academic_years")
