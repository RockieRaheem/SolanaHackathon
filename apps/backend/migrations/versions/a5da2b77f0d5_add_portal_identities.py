"""add portal identities

Revision ID: a5da2b77f0d5
Revises: 9d2a6f08c4b1
Create Date: 2026-10-16 14:14:06.950731
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5da2b77f0d5"
down_revision: str | None = "9d2a6f08c4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_profiles",
        sa.Column("auth_user_id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("preferred_workspace", sa.String(16)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "preferred_workspace is null or preferred_workspace in "
            "('school','guardian','donor')",
            name="ck_portal_profiles_workspace",
        ),
    )
    op.create_table(
        "donor_profiles",
        sa.Column("auth_user_id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("show_public_name", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "guardian_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "guardian_link_id",
            sa.Uuid(),
            sa.ForeignKey("guardian_links.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_email", sa.String(254), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status in ('pending','accepted','revoked','expired')",
            name="ck_guardian_invitations_status",
        ),
    )
    op.create_index(
        "ix_guardian_invitations_school_status",
        "guardian_invitations",
        ["school_id", "status"],
    )
    op.create_index(
        "ix_guardian_invitations_school_id", "guardian_invitations", ["school_id"]
    )
    op.create_index(
        "ix_guardian_invitations_guardian_link_id",
        "guardian_invitations",
        ["guardian_link_id"],
    )
    op.create_index(
        "ix_guardian_invitations_expires_at", "guardian_invitations", ["expires_at"]
    )
    op.create_table(
        "guardian_account_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "guardian_link_id",
            sa.Uuid(),
            sa.ForeignKey("guardian_links.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invitation_id",
            sa.Uuid(),
            sa.ForeignKey("guardian_invitations.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "guardian_link_id", name="uq_guardian_account_links_guardian"
        ),
        sa.UniqueConstraint(
            "auth_user_id",
            "guardian_link_id",
            name="uq_guardian_account_links_user_guardian",
        ),
    )
    op.create_index(
        "ix_guardian_account_links_user_school",
        "guardian_account_links",
        ["auth_user_id", "school_id"],
    )
    op.create_index(
        "ix_guardian_account_links_auth_user_id", "guardian_account_links", ["auth_user_id"]
    )
    op.create_index(
        "ix_guardian_account_links_school_id", "guardian_account_links", ["school_id"]
    )
    op.create_index(
        "ix_guardian_account_links_guardian_link_id",
        "guardian_account_links",
        ["guardian_link_id"],
    )

    for table in (
        "portal_profiles",
        "donor_profiles",
        "guardian_invitations",
        "guardian_account_links",
    ):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    for table in ("portal_profiles", "donor_profiles"):
        op.execute(
            f"""
            CREATE POLICY {table}_owner_select ON public."{table}"
            FOR SELECT TO authenticated
            USING ((SELECT auth.uid()) = auth_user_id)
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_owner_write ON public."{table}"
            FOR ALL TO authenticated
            USING ((SELECT auth.uid()) = auth_user_id)
            WITH CHECK ((SELECT auth.uid()) = auth_user_id)
            """
        )
    op.execute(
        """
        CREATE POLICY guardian_invitations_school_select ON public.guardian_invitations
        FOR SELECT TO authenticated
        USING (private.has_school_role(
            school_id, ARRAY['owner','bursar','auditor']::text[]
        ))
        """
    )
    op.execute(
        """
        CREATE POLICY guardian_invitations_school_write ON public.guardian_invitations
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        """
    )
    op.execute(
        """
        CREATE POLICY guardian_account_links_scoped_select ON public.guardian_account_links
        FOR SELECT TO authenticated
        USING (
            (SELECT auth.uid()) = auth_user_id
            OR private.has_school_role(
                school_id, ARRAY['owner','bursar','auditor']::text[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY guardian_account_links_school_write ON public.guardian_account_links
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        """
    )
    for table in ("guardian_invitations", "guardian_account_links"):
        op.execute(
            f'CREATE TRIGGER audit_{table}_insert AFTER INSERT ON public."{table}" '
            "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
        )
        op.execute(
            f'CREATE TRIGGER audit_{table}_update AFTER UPDATE ON public."{table}" '
            "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
        )


def downgrade() -> None:
    for table in ("guardian_account_links", "guardian_invitations"):
        op.execute(f'DROP TRIGGER audit_{table}_update ON public."{table}"')
        op.execute(f'DROP TRIGGER audit_{table}_insert ON public."{table}"')
    op.drop_table("guardian_account_links")
    op.drop_table("guardian_invitations")
    op.drop_table("donor_profiles")
    op.drop_table("portal_profiles")
