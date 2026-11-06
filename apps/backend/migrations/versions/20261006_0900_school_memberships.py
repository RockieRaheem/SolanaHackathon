"""Bind authenticated users to one institution.

Revision ID: 20261006_0900
Revises: 20261005_1200
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0900"
down_revision: str | None = "20261005_1200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "school_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth_user_id", name="uq_school_memberships_auth_user"),
    )
    op.create_index(
        "ix_school_memberships_auth_user_id",
        "school_memberships",
        ["auth_user_id"],
    )
    # Preserve the existing single-school workspace during the move to tenant membership.
    # Ambiguous installations are intentionally left for explicit onboarding instead.
    op.execute(
        """
        INSERT INTO school_memberships (id, school_id, auth_user_id, role)
        SELECT gen_random_uuid(), schools.id, auth.users.id, 'owner_bursar'
        FROM schools CROSS JOIN auth.users
        WHERE (SELECT count(*) FROM schools) = 1
          AND (SELECT count(*) FROM auth.users) = 1
        """
    )
    op.execute("ALTER TABLE school_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE school_memberships FROM anon, authenticated")


def downgrade() -> None:
    op.drop_index("ix_school_memberships_auth_user_id", table_name="school_memberships")
    op.drop_table("school_memberships")
