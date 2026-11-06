"""Add sponsor programmes and beneficiary allocations.

Revision ID: 20260916_1700
Revises: 20260916_1300
"""

# ruff: noqa: E501
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_1700"
down_revision: str | None = "20260916_1300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sponsors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("sponsor_type", sa.String(30), nullable=False),
        sa.Column("country", sa.String(80), server_default="Uganda", nullable=False),
        sa.Column("verification_status", sa.String(20), server_default="verified", nullable=False),
    )
    op.create_table(
        "funding_programmes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sponsor_id", sa.Uuid(), sa.ForeignKey("sponsors.id"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("budget", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("budget > 0", name="ck_funding_programmes_budget"),
    )
    op.create_table(
        "programme_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "programme_id", sa.Uuid(), sa.ForeignKey("funding_programmes.id"), nullable=False
        ),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("beneficiary_ref", sa.String(32), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UGX", nullable=False),
        sa.Column("status", sa.String(20), server_default="allocated", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_programme_allocations_amount"),
        sa.UniqueConstraint("programme_id", "student_id"),
    )
    op.create_index("ix_programme_allocations_programme", "programme_allocations", ["programme_id"])
    for table in ("sponsors", "funding_programmes", "programme_allocations"):
        op.execute(f'alter table public."{table}" enable row level security')
        op.execute(f'revoke all on table public."{table}" from anon, authenticated')
    for table in ("funding_programmes", "programme_allocations"):
        op.execute(
            f'create trigger audit_{table}_insert after insert on public."{table}" for each row execute function public.capture_audit_event()'
        )  # noqa: E501
        op.execute(
            f'create trigger audit_{table}_update after update on public."{table}" for each row execute function public.capture_audit_event()'
        )  # noqa: E501


def downgrade() -> None:
    op.drop_table("programme_allocations")
    op.drop_table("funding_programmes")
    op.drop_table("sponsors")
