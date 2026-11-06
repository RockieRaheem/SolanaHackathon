"""add controlled term billing

Revision ID: 81d7c62772c3
Revises: 20e3e44669b3
Create Date: 2026-10-11 13:16:16.481056
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "81d7c62772c3"
down_revision: str | None = "20e3e44669b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_policy(table: str, expression: str) -> None:
    read_roles = "ARRAY['owner','bursar','cashier','auditor']::text[]"
    write_roles = "ARRAY['owner','bursar']::text[]"
    op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute(
        f"CREATE POLICY {table}_tenant_select ON public.\"{table}\" "
        f"FOR SELECT TO authenticated USING "
        f"(private.has_school_role({expression}, {read_roles}))"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_write ON public.\"{table}\" "
        f"FOR ALL TO authenticated USING "
        f"(private.has_school_role({expression}, {write_roles})) WITH CHECK "
        f"(private.has_school_role({expression}, {write_roles}))"
    )


def upgrade() -> None:
    op.create_table(
        "billing_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("preview_token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="posted", nullable=False),
        sa.Column("learner_count", sa.Integer(), nullable=False),
        sa.Column("charge_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("credit_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status = 'posted'", name="ck_billing_publications_status"),
        sa.ForeignKeyConstraint(["period_id"], ["academic_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "school_id", "period_id", "idempotency_key", name="uq_billing_publication_key"
        ),
    )
    for column in ("school_id", "period_id"):
        op.create_index(f"ix_billing_publications_{column}", "billing_publications", [column])

    op.add_column("fee_structures", sa.Column("stream_id", sa.Uuid()))
    op.add_column(
        "fee_structures",
        sa.Column("target_type", sa.String(16), server_default="cohort", nullable=False),
    )
    op.add_column("fee_structures", sa.Column("boarding_status", sa.String(20)))
    op.add_column(
        "fee_structures",
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
    )
    op.add_column(
        "fee_structures",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("fee_structures", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_fee_structures_stream_id", "fee_structures", "streams", ["stream_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_fee_structures_target_type",
        "fee_structures",
        "target_type in ('cohort', 'selected')",
    )
    op.create_check_constraint(
        "ck_fee_structures_boarding_status",
        "fee_structures",
        "boarding_status is null or boarding_status in ('day', 'boarding', 'half_boarding')",
    )
    op.create_check_constraint(
        "ck_fee_structures_status",
        "fee_structures",
        "status in ('draft', 'published')",
    )
    op.execute(
        """
        DO $$ DECLARE target_constraint text;
        BEGIN
          SELECT conname INTO target_constraint FROM pg_constraint
          WHERE conrelid = 'public.fee_structures'::regclass AND contype = 'u'
            AND pg_get_constraintdef(oid) =
                'UNIQUE (school_id, class_id, academic_year, term)';
          IF target_constraint IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.fee_structures DROP CONSTRAINT %I',
                           target_constraint);
          END IF;
        END $$
        """
    )
    op.create_index(
        "ix_fee_structures_period_target",
        "fee_structures",
        ["period_id", "class_id", "stream_id"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_structures_cohort_target ON fee_structures (
          period_id, class_id,
          COALESCE(stream_id, '00000000-0000-0000-0000-000000000000'::uuid),
          COALESCE(boarding_status, '')
        ) WHERE target_type = 'cohort' AND is_active
        """
    )
    op.execute(
        "ALTER TABLE fee_structures DISABLE TRIGGER fee_structures_reject_closed_period"
    )
    op.execute(
        """
        UPDATE fee_structures fs SET status = 'published', published_at = now()
        WHERE EXISTS (
          SELECT 1 FROM student_fee_assignments a WHERE a.fee_structure_id = fs.id
        )
        """
    )
    op.execute(
        "ALTER TABLE fee_structures ENABLE TRIGGER fee_structures_reject_closed_period"
    )
    op.create_table(
        "fee_structure_learners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fee_structure_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fee_structure_id"], ["fee_structures.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fee_structure_id", "student_id"),
    )
    for column in ("fee_structure_id", "student_id"):
        op.create_index(f"ix_fee_structure_learners_{column}", "fee_structure_learners", [column])

    op.add_column(
        "installment_rules",
        sa.Column("calculation_type", sa.String(16), server_default="fixed", nullable=False),
    )
    op.add_column("installment_rules", sa.Column("percentage", sa.Numeric(7, 4)))
    op.create_check_constraint(
        "ck_installment_rules_calculation",
        "installment_rules",
        "(calculation_type = 'fixed' and percentage is null) or "
        "(calculation_type = 'percentage' and percentage > 0 and percentage <= 100)",
    )

    op.add_column("requirements", sa.Column("stream_id", sa.Uuid()))
    op.add_column("requirements", sa.Column("boarding_status", sa.String(20)))
    op.add_column(
        "requirements",
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
    )
    op.create_foreign_key(
        "fk_requirements_stream_id", "requirements", "streams", ["stream_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_requirements_boarding_status",
        "requirements",
        "boarding_status is null or boarding_status in ('day', 'boarding', 'half_boarding')",
    )
    op.create_check_constraint(
        "ck_requirements_status", "requirements", "status in ('draft', 'published')"
    )
    op.execute(
        "ALTER TABLE requirements DISABLE TRIGGER requirements_reject_closed_period"
    )
    op.execute(
        """
        UPDATE requirements r SET status = 'published' WHERE EXISTS (
          SELECT 1 FROM student_requirements a WHERE a.requirement_id = r.id
        )
        """
    )
    op.execute(
        "ALTER TABLE requirements ENABLE TRIGGER requirements_reject_closed_period"
    )
    op.create_table(
        "requirement_learners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "student_id"),
    )
    for column in ("requirement_id", "student_id"):
        op.create_index(f"ix_requirement_learners_{column}", "requirement_learners", [column])

    op.add_column("student_fee_assignments", sa.Column("publication_id", sa.Uuid()))
    op.create_index(
        "ix_student_fee_assignments_publication_id",
        "student_fee_assignments",
        ["publication_id"],
    )
    op.create_foreign_key(
        "fk_student_fee_assignments_publication_id",
        "student_fee_assignments",
        "billing_publications",
        ["publication_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("student_requirements", sa.Column("publication_id", sa.Uuid()))
    op.add_column("student_requirements", sa.Column("waiver_reason", sa.String(240)))
    op.create_index(
        "ix_student_requirements_publication_id", "student_requirements", ["publication_id"]
    )
    op.create_foreign_key(
        "fk_student_requirements_publication_id",
        "student_requirements",
        "billing_publications",
        ["publication_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "billing_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid()),
        sa.Column("publication_id", sa.Uuid()),
        sa.Column("adjustment_type", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("description", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_billing_adjustments_amount"),
        sa.CheckConstraint(
            "adjustment_type in ('addition','discount','sponsorship_credit','waiver')",
            name="ck_billing_adjustments_type",
        ),
        sa.CheckConstraint(
            "status in ('draft','published')", name="ck_billing_adjustments_status"
        ),
        sa.ForeignKeyConstraint(["category_id"], ["fee_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["period_id"], ["academic_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["billing_publications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("school_id", "period_id", "student_id", "publication_id"):
        op.create_index(f"ix_billing_adjustments_{column}", "billing_adjustments", [column])
    op.create_index(
        "ix_billing_adjustments_period_student",
        "billing_adjustments",
        ["period_id", "student_id"],
    )

    for name, column_type in (
        ("school_id", sa.Uuid()),
        ("period_id", sa.Uuid()),
        ("description", sa.String(240)),
        ("publication_id", sa.Uuid()),
        ("fee_assignment_id", sa.Uuid()),
        ("requirement_assignment_id", sa.Uuid()),
        ("billing_adjustment_id", sa.Uuid()),
    ):
        op.add_column("ledger_entries", sa.Column(name, column_type))
    op.execute(
        "UPDATE ledger_entries e SET school_id = s.school_id FROM students s "
        "WHERE s.id = e.student_id"
    )
    op.execute(
        "UPDATE ledger_entries e SET period_id = p.period_id FROM payments p "
        "WHERE p.id = e.payment_id"
    )
    op.execute(
        """
        WITH candidates AS (
          SELECT DISTINCT ON (e.id) e.id entry_id, a.id assignment_id, f.period_id
          FROM ledger_entries e
          JOIN student_fee_assignments a ON a.student_id = e.student_id
          JOIN fee_structures f ON f.id = a.fee_structure_id
          WHERE e.entry_type = 'charge' AND e.period_id IS NULL
          ORDER BY e.id, a.assigned_at
        )
        UPDATE ledger_entries e SET period_id = c.period_id,
          fee_assignment_id = c.assignment_id
        FROM candidates c WHERE c.entry_id = e.id
        """
    )
    op.execute(
        """
        UPDATE ledger_entries e SET requirement_assignment_id = a.id,
          period_id = r.period_id
        FROM student_requirements a JOIN requirements r ON r.id = a.requirement_id
        WHERE e.reference = 'REQ:' || a.id::text
        """
    )
    op.execute(
        """
        UPDATE ledger_entries e SET period_id = recent.period_id FROM (
          SELECT DISTINCT ON (student_id) student_id, period_id FROM enrollments
          ORDER BY student_id, academic_year DESC, term DESC
        ) recent WHERE recent.student_id = e.student_id AND e.period_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE ledger_entries e SET period_id = recent.period_id FROM (
          SELECT DISTINCT ON (school_id) school_id, id period_id
          FROM academic_periods
          ORDER BY school_id, opening_date DESC, sequence DESC
        ) recent WHERE recent.school_id = e.school_id AND e.period_id IS NULL
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM ledger_entries WHERE school_id IS NULL OR period_id IS NULL
          ) THEN
            RAISE EXCEPTION
              'Cannot migrate ledger entries without a school and academic period';
          END IF;
        END $$
        """
    )
    op.alter_column("ledger_entries", "school_id", nullable=False)
    op.alter_column("ledger_entries", "period_id", nullable=False)
    for column in ("school_id", "period_id", "publication_id"):
        op.create_index(f"ix_ledger_entries_{column}", "ledger_entries", [column])
    op.create_index(
        "ix_ledger_entries_period_student", "ledger_entries", ["period_id", "student_id"]
    )
    for name, column in (
        ("uq_ledger_entries_fee_assignment", "fee_assignment_id"),
        ("uq_ledger_entries_requirement_assignment", "requirement_assignment_id"),
        ("uq_ledger_entries_billing_adjustment", "billing_adjustment_id"),
    ):
        op.create_unique_constraint(name, "ledger_entries", [column])
    for name, target, column in (
        ("fk_ledger_entries_school_id", "schools", "school_id"),
        ("fk_ledger_entries_period_id", "academic_periods", "period_id"),
        ("fk_ledger_entries_publication_id", "billing_publications", "publication_id"),
        ("fk_ledger_entries_fee_assignment_id", "student_fee_assignments", "fee_assignment_id"),
        (
            "fk_ledger_entries_requirement_assignment_id",
            "student_requirements",
            "requirement_assignment_id",
        ),
        ("fk_ledger_entries_billing_adjustment_id", "billing_adjustments", "billing_adjustment_id"),
    ):
        op.create_foreign_key(
            name, "ledger_entries", target, [column], ["id"], ondelete="RESTRICT"
        )

    _tenant_policy("billing_publications", "school_id")
    _tenant_policy("billing_adjustments", "school_id")
    _tenant_policy(
        "fee_structure_learners",
        "(SELECT school_id FROM public.fee_structures "
        "WHERE id = fee_structure_learners.fee_structure_id)",
    )
    _tenant_policy(
        "requirement_learners",
        "(SELECT school_id FROM public.requirements "
        "WHERE id = requirement_learners.requirement_id)",
    )
    op.execute(
        """
        CREATE FUNCTION private.reject_ledger_mutation()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN RAISE EXCEPTION 'Posted ledger entries are immutable'; END; $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION private.reject_ledger_mutation() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER ledger_entries_immutable BEFORE UPDATE OR DELETE ON ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION private.reject_ledger_mutation()"
    )
    for table in ("billing_publications", "billing_adjustments", "ledger_entries"):
        op.execute(
            f"CREATE TRIGGER {table}_reject_closed_period "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION private.reject_closed_period_mutation()"
        )


def downgrade() -> None:
    for table in ("ledger_entries", "billing_adjustments", "billing_publications"):
        op.execute(f"DROP TRIGGER {table}_reject_closed_period ON {table}")
    op.execute("DROP TRIGGER ledger_entries_immutable ON ledger_entries")
    op.execute("DROP FUNCTION private.reject_ledger_mutation()")
    for name in (
        "fk_ledger_entries_billing_adjustment_id",
        "fk_ledger_entries_requirement_assignment_id",
        "fk_ledger_entries_fee_assignment_id",
        "fk_ledger_entries_publication_id",
        "fk_ledger_entries_period_id",
        "fk_ledger_entries_school_id",
    ):
        op.drop_constraint(name, "ledger_entries", type_="foreignkey")
    for name in (
        "uq_ledger_entries_billing_adjustment",
        "uq_ledger_entries_requirement_assignment",
        "uq_ledger_entries_fee_assignment",
    ):
        op.drop_constraint(name, "ledger_entries", type_="unique")
    op.drop_index("ix_ledger_entries_period_student", table_name="ledger_entries")
    for column in ("publication_id", "period_id", "school_id"):
        op.drop_index(f"ix_ledger_entries_{column}", table_name="ledger_entries")
    for column in (
        "billing_adjustment_id",
        "requirement_assignment_id",
        "fee_assignment_id",
        "publication_id",
        "description",
        "period_id",
        "school_id",
    ):
        op.drop_column("ledger_entries", column)
    op.drop_table("billing_adjustments")
    op.drop_constraint(
        "fk_student_requirements_publication_id", "student_requirements", type_="foreignkey"
    )
    op.drop_index("ix_student_requirements_publication_id", table_name="student_requirements")
    op.drop_column("student_requirements", "waiver_reason")
    op.drop_column("student_requirements", "publication_id")
    op.drop_constraint(
        "fk_student_fee_assignments_publication_id",
        "student_fee_assignments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_student_fee_assignments_publication_id", table_name="student_fee_assignments"
    )
    op.drop_column("student_fee_assignments", "publication_id")
    op.drop_table("requirement_learners")
    op.drop_constraint("ck_requirements_status", "requirements", type_="check")
    op.drop_constraint("ck_requirements_boarding_status", "requirements", type_="check")
    op.drop_constraint("fk_requirements_stream_id", "requirements", type_="foreignkey")
    for column in ("status", "boarding_status", "stream_id"):
        op.drop_column("requirements", column)
    op.drop_constraint("ck_installment_rules_calculation", "installment_rules", type_="check")
    op.drop_column("installment_rules", "percentage")
    op.drop_column("installment_rules", "calculation_type")
    op.drop_table("fee_structure_learners")
    op.execute("DROP INDEX uq_fee_structures_cohort_target")
    op.drop_index("ix_fee_structures_period_target", table_name="fee_structures")
    op.drop_constraint("ck_fee_structures_status", "fee_structures", type_="check")
    op.drop_constraint("ck_fee_structures_boarding_status", "fee_structures", type_="check")
    op.drop_constraint("ck_fee_structures_target_type", "fee_structures", type_="check")
    op.drop_constraint("fk_fee_structures_stream_id", "fee_structures", type_="foreignkey")
    for column in (
        "published_at",
        "created_at",
        "status",
        "boarding_status",
        "target_type",
        "stream_id",
    ):
        op.drop_column("fee_structures", column)
    op.create_unique_constraint(
        "uq_fee_structures_legacy_period",
        "fee_structures",
        ["school_id", "class_id", "academic_year", "term"],
    )
    op.drop_table("billing_publications")
