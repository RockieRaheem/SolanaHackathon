"""Add separately consented public campaign media."""

import sqlalchemy as sa
from alembic import op

revision = "a3d8e71c5f20"
down_revision = "f7a2d41e6c93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_referrals",
        sa.Column("public_media_consent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "support_consents",
        sa.Column("public_media_consent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "support_campaign_media",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id", sa.Uuid(), sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("alt_text", sa.String(160), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="approved", nullable=False),
        sa.Column("approved_by", sa.String(120), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("removed_by", sa.String(120)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status in ('approved','removed')", name="ck_support_campaign_media_status"
        ),
    )
    op.create_index("ix_support_campaign_media_case_id", "support_campaign_media", ["case_id"])
    op.create_index(
        "ix_support_campaign_media_school_id", "support_campaign_media", ["school_id"]
    )
    op.create_index(
        "ix_support_campaign_media_school_status",
        "support_campaign_media", ["school_id", "status"],
    )
    op.execute("ALTER TABLE public.support_campaign_media ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE public.support_campaign_media FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY support_campaign_media_owner_access ON public.support_campaign_media
        FOR ALL TO authenticated USING (
            private.has_school_role(school_id, ARRAY['owner']::text[])
        ) WITH CHECK (
            private.has_school_role(school_id, ARRAY['owner']::text[])
        )
        """
    )


def downgrade() -> None:
    op.drop_table("support_campaign_media")
    op.drop_column("support_consents", "public_media_consent")
    op.drop_column("support_referrals", "public_media_consent")
