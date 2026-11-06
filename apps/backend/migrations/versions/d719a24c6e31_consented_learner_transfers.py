"""add consented learner transfers

Revision ID: d719a24c6e31
Revises: ce42d91f5a10
Create Date: 2026-10-22 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d719a24c6e31"
down_revision: str | None = "ce42d91f5a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learner_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("school_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_learner_identities_organization_id", "learner_identities", ["organization_id"]
    )
    op.add_column("students", sa.Column("learner_identity_id", sa.Uuid()))
    op.execute(
        """
        INSERT INTO learner_identities (id, organization_id)
        SELECT students.id, schools.organization_id
        FROM students JOIN schools ON schools.id = students.school_id
        """
    )
    op.execute("UPDATE students SET learner_identity_id = id")
    op.alter_column("students", "learner_identity_id", nullable=False)
    op.create_foreign_key(
        "fk_students_learner_identity_id",
        "students",
        "learner_identities",
        ["learner_identity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_students_learner_identity_id", "students", ["learner_identity_id"])
    op.drop_constraint("students_learner_identification_number_key", "students", type_="unique")
    op.create_unique_constraint(
        "uq_students_school_learner_identification",
        "students",
        ["school_id", "learner_identification_number"],
    )
    op.create_unique_constraint(
        "uq_students_school_learner_identity",
        "students",
        ["school_id", "learner_identity_id"],
    )
    op.create_table(
        "learner_transfer_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reference", sa.String(24), nullable=False, unique=True),
        sa.Column(
            "source_school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_student_id",
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
        sa.Column(
            "target_student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False),
        sa.Column("consent_method", sa.String(24), nullable=False),
        sa.Column("consent_reference", sa.String(120), nullable=False),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("learner_first_name", sa.String(80), nullable=False),
        sa.Column("learner_middle_name", sa.String(80)),
        sa.Column("learner_last_name", sa.String(80), nullable=False),
        sa.Column("learner_date_of_birth", sa.Date()),
        sa.Column("learner_gender", sa.String(16), nullable=False),
        sa.Column("learner_identification_number", sa.String(40)),
        sa.Column("learner_boarding_status", sa.String(20), nullable=False),
        sa.Column("learner_nationality", sa.String(60), nullable=False),
        sa.Column("guardian_first_name", sa.String(80), nullable=False),
        sa.Column("guardian_last_name", sa.String(80), nullable=False),
        sa.Column("guardian_relationship", sa.String(30), nullable=False),
        sa.Column("guardian_phone", sa.String(32)),
        sa.Column("guardian_email", sa.String(254)),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column("decided_by", sa.String(254)),
        sa.Column("decision_reason", sa.String(240)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status in ('pending','accepted','rejected','cancelled')",
            name="ck_learner_transfer_cases_status",
        ),
        sa.CheckConstraint(
            "consent_method in ('written','digital','recorded_call','in_person')",
            name="ck_learner_transfer_cases_consent_method",
        ),
    )
    for name, columns in (
        ("ix_learner_transfers_source_status", ["source_school_id", "status"]),
        ("ix_learner_transfers_target_status", ["target_school_id", "status"]),
        ("ix_learner_transfer_cases_source_school_id", ["source_school_id"]),
        ("ix_learner_transfer_cases_target_school_id", ["target_school_id"]),
        ("ix_learner_transfer_cases_source_student_id", ["source_student_id"]),
    ):
        op.create_index(name, "learner_transfer_cases", columns)
    op.create_index(
        "uq_learner_transfer_pending_target",
        "learner_transfer_cases",
        ["source_student_id", "target_school_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    for table in ("learner_identities", "learner_transfer_cases"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute(
        """
        CREATE POLICY learner_transfer_cases_unit_access ON public.learner_transfer_cases
        FOR SELECT TO authenticated USING (
            private.has_school_role(source_school_id, ARRAY['owner','bursar','auditor']::text[])
            OR private.has_school_role(target_school_id, ARRAY['owner','bursar','auditor']::text[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY learner_transfer_cases_unit_write ON public.learner_transfer_cases
        FOR ALL TO authenticated USING (
            private.has_school_role(source_school_id, ARRAY['owner','bursar']::text[])
            OR private.has_school_role(target_school_id, ARRAY['owner','bursar']::text[])
        ) WITH CHECK (
            private.has_school_role(source_school_id, ARRAY['owner','bursar']::text[])
            OR private.has_school_role(target_school_id, ARRAY['owner','bursar']::text[])
        )
        """
    )


def downgrade() -> None:
    op.drop_table("learner_transfer_cases")
    op.drop_constraint("uq_students_school_learner_identity", "students", type_="unique")
    op.drop_constraint("uq_students_school_learner_identification", "students", type_="unique")
    op.create_unique_constraint(
        "students_learner_identification_number_key",
        "students",
        ["learner_identification_number"],
    )
    op.drop_index("ix_students_learner_identity_id", table_name="students")
    op.drop_constraint("fk_students_learner_identity_id", "students", type_="foreignkey")
    op.drop_column("students", "learner_identity_id")
    op.drop_table("learner_identities")
