"""add support assistant usage controls

Revision ID: a91d38c7e5f2
Revises: f6a91c42d7e0
Create Date: 2026-10-22 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91d38c7e5f2"
down_revision: str | None = "f6a91c42d7e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_assistant_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT")
        ),
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column("persona", sa.String(16), nullable=False),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.Uuid()),
        sa.Column("model_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), server_default="started", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "persona in ('guardian','donor','school')",
            name="ck_support_assistant_usage_persona",
        ),
        sa.CheckConstraint(
            "status in ('started','completed','failed','blocked')",
            name="ck_support_assistant_usage_status",
        ),
    )
    op.create_index(
        "ix_support_assistant_usage_school_id", "support_assistant_usage", ["school_id"]
    )
    op.create_index(
        "ix_support_assistant_usage_auth_user_id",
        "support_assistant_usage",
        ["auth_user_id"],
    )
    op.create_index(
        "ix_support_assistant_usage_scope_id", "support_assistant_usage", ["scope_id"]
    )
    op.create_index(
        "ix_support_assistant_usage_user_time",
        "support_assistant_usage",
        ["auth_user_id", "persona", "created_at"],
    )
    op.create_index(
        "ix_support_assistant_usage_school_time",
        "support_assistant_usage",
        ["school_id", "created_at"],
    )
    op.execute("ALTER TABLE public.support_assistant_usage ENABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE ALL ON TABLE public.support_assistant_usage FROM anon, authenticated"
    )
    op.execute(
        """
        CREATE POLICY support_assistant_usage_owner_access
        ON public.support_assistant_usage FOR ALL TO authenticated
        USING (school_id IS NOT NULL AND
               private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (school_id IS NOT NULL AND
                    private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )


def downgrade() -> None:
    op.drop_table("support_assistant_usage")
