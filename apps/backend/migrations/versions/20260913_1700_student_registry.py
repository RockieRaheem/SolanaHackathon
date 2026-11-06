"""Create the student registry.

Revision ID: 20260913_1700
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_1700"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("emis_code", sa.String(40), unique=True),
        sa.Column("district", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "academic_classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("school_id", "name"),
    )
    op.create_table(
        "streams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("academic_classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(40), nullable=False),
        sa.UniqueConstraint("class_id", "name"),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("middle_name", sa.String(80)),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("email", sa.String(254)),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("people.id"), unique=True, nullable=False),
        sa.Column("admission_no", sa.String(40), nullable=False),
        sa.Column("learner_identification_number", sa.String(40), unique=True),
        sa.Column("gender", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("boarding_status", sa.String(20), server_default="day", nullable=False),
        sa.Column("nationality", sa.String(60), server_default="Ugandan", nullable=False),
        sa.Column("previous_school", sa.String(160)),
        sa.Column("special_needs", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("school_id", "admission_no"),
        sa.CheckConstraint("gender in ('male', 'female', 'other')", name="ck_students_gender"),
        sa.CheckConstraint(
            "status in ('active', 'transferred', 'withdrawn', 'completed', 'archived')",
            name="ck_students_status",
        ),
    )
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("academic_classes.id"), nullable=False),
        sa.Column("stream_id", sa.Uuid(), sa.ForeignKey("streams.id")),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.Integer(), nullable=False),
        sa.Column(
            "enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("student_id", "academic_year", "term"),
        sa.CheckConstraint("term between 1 and 3", name="ck_enrollments_term"),
    )
    op.create_table(
        "guardian_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("can_receive_statements", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("student_id", "person_id"),
    )
    op.create_index("ix_students_school_status", "students", ["school_id", "status"])
    op.create_index("ix_enrollments_class", "enrollments", ["class_id", "academic_year", "term"])

    # Public-schema tables are backend-only until user-scoped Supabase Auth policies are introduced.
    for table in (
        "schools",
        "academic_classes",
        "streams",
        "people",
        "students",
        "enrollments",
        "guardian_links",
    ):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')


def downgrade() -> None:
    op.drop_table("guardian_links")
    op.drop_table("enrollments")
    op.drop_table("students")
    op.drop_table("people")
    op.drop_table("streams")
    op.drop_table("academic_classes")
    op.drop_table("schools")
