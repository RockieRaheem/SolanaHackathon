"""Add private guardian campaign media review."""

import sqlalchemy as sa
from alembic import op

revision = "f2b71a6c9d40"
down_revision = "e8c4a2f9d731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_campaign_media", sa.Column("submitted_by", sa.String(120)))
    op.add_column("support_campaign_media", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("support_campaign_media", sa.Column("review_note", sa.String(500)))
    op.execute(
        "UPDATE support_campaign_media SET submitted_by = approved_by, "
        "submitted_at = approved_at WHERE submitted_by IS NULL"
    )
    op.alter_column("support_campaign_media", "approved_by", nullable=True)
    op.alter_column("support_campaign_media", "approved_at", nullable=True, server_default=None)
    op.drop_constraint(
        "ck_support_campaign_media_status", "support_campaign_media", type_="check"
    )
    op.create_check_constraint(
        "ck_support_campaign_media_status",
        "support_campaign_media",
        "status in ('pending','approved','rejected','removed')",
    )
    op.alter_column("support_campaign_media", "status", server_default="pending")


def downgrade() -> None:
    op.execute(
        "UPDATE support_campaign_media SET status = 'removed', approved_by = COALESCE(approved_by, "
        "submitted_by, 'system'), approved_at = COALESCE(approved_at, submitted_at, now()) "
        "WHERE status IN ('pending','rejected')"
    )
    op.drop_constraint(
        "ck_support_campaign_media_status", "support_campaign_media", type_="check"
    )
    op.create_check_constraint(
        "ck_support_campaign_media_status",
        "support_campaign_media",
        "status in ('approved','removed')",
    )
    op.alter_column("support_campaign_media", "status", server_default="approved")
    op.alter_column(
        "support_campaign_media", "approved_at", nullable=False, server_default=sa.func.now()
    )
    op.alter_column("support_campaign_media", "approved_by", nullable=False)
    op.drop_column("support_campaign_media", "review_note")
    op.drop_column("support_campaign_media", "submitted_at")
    op.drop_column("support_campaign_media", "submitted_by")
