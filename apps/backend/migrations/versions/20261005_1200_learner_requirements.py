"""Add class requirements, learner fulfilment, and payment purpose allocation.

Revision ID: 20261005_1200
Revises: 076b76b8a490
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_1200"
down_revision: str | None = "076b76b8a490"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("requirement_type", sa.String(24), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), server_default="1", nullable=False),
        sa.Column("unit", sa.String(30), server_default="item", nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("is_mandatory", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("term between 1 and 3", name="ck_requirements_term"),
        sa.CheckConstraint("amount >= 0", name="ck_requirements_amount"),
        sa.CheckConstraint("quantity > 0", name="ck_requirements_quantity"),
        sa.CheckConstraint(
            "requirement_type in ('payment', 'school_item', 'bring_item', 'document')",
            name="ck_requirements_type",
        ),
        sa.UniqueConstraint("school_id", "code", "academic_year", "term"),
    )
    op.create_index(
        "ix_requirements_school_period",
        "requirements",
        ["school_id", "academic_year", "term"],
    )
    op.create_table(
        "requirement_classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "requirement_id",
            sa.Uuid(),
            sa.ForeignKey("requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("academic_classes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("requirement_id", "class_id"),
    )
    op.create_index("ix_requirement_classes_class", "requirement_classes", ["class_id"])
    op.create_table(
        "student_requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "requirement_id",
            sa.Uuid(),
            sa.ForeignKey("requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("fulfilled_quantity", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("is_waived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True)),
        sa.Column("fulfilment_note", sa.String(240)),
        sa.CheckConstraint("expected_amount >= 0", name="ck_student_requirements_amount"),
        sa.CheckConstraint("expected_quantity > 0", name="ck_student_requirements_quantity"),
        sa.CheckConstraint("fulfilled_quantity >= 0", name="ck_student_requirements_fulfilled"),
        sa.UniqueConstraint("requirement_id", "student_id"),
    )
    op.create_index("ix_student_requirements_student", "student_requirements", ["student_id"])
    op.add_column(
        "payment_allocations", sa.Column("requirement_assignment_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_payment_allocations_requirement_assignment",
        "payment_allocations",
        "student_requirements",
        ["requirement_assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_payment_allocations_requirement",
        "payment_allocations",
        ["requirement_assignment_id"],
    )
    for table in ("requirements", "requirement_classes", "student_requirements"):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')


def downgrade() -> None:
    op.drop_index("ix_payment_allocations_requirement", table_name="payment_allocations")
    op.drop_constraint(
        "fk_payment_allocations_requirement_assignment",
        "payment_allocations",
        type_="foreignkey",
    )
    op.drop_column("payment_allocations", "requirement_assignment_id")
    op.drop_index("ix_student_requirements_student", table_name="student_requirements")
    op.drop_table("student_requirements")
    op.drop_index("ix_requirement_classes_class", table_name="requirement_classes")
    op.drop_table("requirement_classes")
    op.drop_index("ix_requirements_school_period", table_name="requirements")
    op.drop_table("requirements")
