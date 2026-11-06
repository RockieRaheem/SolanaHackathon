"""add staff access lifecycle

Revision ID: ce42d91f5a10
Revises: b821c109d4e7
Create Date: 2026-10-22 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ce42d91f5a10"
down_revision: str | None = "b821c109d4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("school_memberships", sa.Column("member_email", sa.String(254)))
    op.execute(
        """
        UPDATE school_memberships AS membership
        SET member_email = lower(users.email)
        FROM auth.users AS users
        WHERE users.id = membership.auth_user_id
        """
    )
    op.create_table(
        "staff_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("invited_email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role in ('bursar','cashier','auditor')", name="ck_staff_invitations_role"
        ),
        sa.CheckConstraint(
            "status in ('pending','accepted','revoked','expired')",
            name="ck_staff_invitations_status",
        ),
    )
    op.create_index("ix_staff_invitations_school_id", "staff_invitations", ["school_id"])
    op.create_index("ix_staff_invitations_expires_at", "staff_invitations", ["expires_at"])
    op.create_index(
        "ix_staff_invitations_school_status", "staff_invitations", ["school_id", "status"]
    )
    op.create_index(
        "uq_staff_invitations_pending_email",
        "staff_invitations",
        ["school_id", "invited_email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute("ALTER TABLE staff_invitations ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE staff_invitations FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY staff_invitations_owner_access ON public.staff_invitations
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )


def downgrade() -> None:
    op.drop_table("staff_invitations")
    op.drop_column("school_memberships", "member_email")
