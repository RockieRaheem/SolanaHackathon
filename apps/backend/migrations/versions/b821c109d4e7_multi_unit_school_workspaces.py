"""add multi-unit school workspaces

Revision ID: b821c109d4e7
Revises: 7ac4d92e1b63
Create Date: 2026-10-21 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b821c109d4e7"
down_revision: str | None = "7ac4d92e1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "school_organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("emis_code", sa.String(length=40), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("emis_code"),
    )
    op.add_column(
        "schools", sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "schools",
        sa.Column("unit_name", sa.String(length=80), server_default="Main section", nullable=False),
    )
    op.add_column(
        "schools",
        sa.Column("unit_type", sa.String(length=32), server_default="custom", nullable=False),
    )
    op.execute(
        """
        INSERT INTO school_organizations (id, name, emis_code, district)
        SELECT id, name, emis_code, district FROM schools
        """
    )
    op.execute("UPDATE schools SET organization_id = id, unit_name = name")
    op.alter_column("schools", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_schools_organization_id",
        "schools",
        "school_organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_schools_organization_id", "schools", ["organization_id"])
    op.create_unique_constraint(
        "uq_schools_organization_unit_type", "schools", ["organization_id", "unit_type"]
    )
    op.drop_constraint(
        "uq_school_memberships_auth_user", "school_memberships", type_="unique"
    )
    op.create_unique_constraint(
        "uq_school_memberships_school_user",
        "school_memberships",
        ["school_id", "auth_user_id"],
    )
    op.execute("ALTER TABLE school_organizations ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE school_organizations FROM anon, authenticated")


def downgrade() -> None:
    op.drop_constraint(
        "uq_school_memberships_school_user", "school_memberships", type_="unique"
    )
    op.create_unique_constraint(
        "uq_school_memberships_auth_user", "school_memberships", ["auth_user_id"]
    )
    op.drop_constraint("uq_schools_organization_unit_type", "schools", type_="unique")
    op.drop_index("ix_schools_organization_id", table_name="schools")
    op.drop_constraint("fk_schools_organization_id", "schools", type_="foreignkey")
    op.drop_column("schools", "unit_type")
    op.drop_column("schools", "unit_name")
    op.drop_column("schools", "organization_id")
    op.drop_table("school_organizations")
