"""add support notifications and outcome review

Revision ID: f6a91c42d7e0
Revises: e84a1f03c9b2
Create Date: 2026-10-22 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a91c42d7e0"
down_revision: str | None = "e84a1f03c9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("support_attestations", sa.Column("redacted_statement", sa.String(500)))
    op.add_column(
        "support_attestations",
        sa.Column("status", sa.String(16), server_default="submitted", nullable=False),
    )
    op.add_column("support_attestations", sa.Column("submitted_by_user_id", sa.Uuid()))
    op.add_column(
        "support_attestations",
        sa.Column("submitted_by_role", sa.String(16), server_default="school", nullable=False),
    )
    op.add_column("support_attestations", sa.Column("submitted_by", sa.String(120)))
    op.add_column("support_attestations", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("support_attestations", sa.Column("reviewed_by", sa.String(120)))
    op.add_column("support_attestations", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("support_attestations", sa.Column("rejection_reason", sa.String(240)))
    op.execute(
        """
        UPDATE support_attestations
        SET status = 'approved', redacted_statement = statement,
            submitted_by = verified_by, submitted_at = verified_at,
            reviewed_by = verified_by, reviewed_at = verified_at,
            submitted_by_role = 'school'
        """
    )
    op.alter_column("support_attestations", "submitted_by", nullable=False)
    op.alter_column("support_attestations", "submitted_at", nullable=False)
    op.alter_column("support_attestations", "verified_by", nullable=True)
    op.alter_column("support_attestations", "verified_at", nullable=True, server_default=None)
    op.create_check_constraint(
        "ck_support_attestations_status",
        "support_attestations",
        "status in ('submitted','approved','rejected')",
    )
    op.create_index(
        "ix_support_attestations_school_status",
        "support_attestations",
        ["school_id", "status"],
    )
    op.create_index(
        "ix_support_attestations_submitted_by_user_id",
        "support_attestations",
        ["submitted_by_user_id"],
    )

    op.create_table(
        "support_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("recipient_type", sa.String(16), nullable=False),
        sa.Column("recipient_auth_user_id", sa.Uuid()),
        sa.Column("recipient_email", sa.String(254)),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("href", sa.String(300), nullable=False),
        sa.Column("related_type", sa.String(40), nullable=False),
        sa.Column("related_id", sa.Uuid(), nullable=False),
        sa.Column("dedup_key", sa.String(180), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "recipient_type in ('school','guardian','donor')",
            name="ck_support_notifications_recipient_type",
        ),
    )
    op.create_index("ix_support_notifications_school_id", "support_notifications", ["school_id"])
    op.create_index(
        "ix_support_notifications_recipient_auth_user_id",
        "support_notifications",
        ["recipient_auth_user_id"],
    )
    op.create_index(
        "ix_support_notifications_recipient_email",
        "support_notifications",
        ["recipient_email"],
    )
    op.create_index(
        "ix_support_notifications_school_time",
        "support_notifications",
        ["school_id", "created_at"],
    )
    op.create_index(
        "ix_support_notifications_user_time",
        "support_notifications",
        ["recipient_auth_user_id", "created_at"],
    )
    op.create_index(
        "ix_support_notifications_email_time",
        "support_notifications",
        ["recipient_email", "created_at"],
    )

    op.create_table(
        "support_notification_reads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("support_notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "notification_id", "auth_user_id", name="uq_support_notification_reads"
        ),
    )
    op.create_index(
        "ix_support_notification_reads_notification_id",
        "support_notification_reads",
        ["notification_id"],
    )
    op.create_index(
        "ix_support_notification_reads_auth_user_id",
        "support_notification_reads",
        ["auth_user_id"],
    )
    op.create_index(
        "ix_support_notification_reads_user",
        "support_notification_reads",
        ["auth_user_id", "read_at"],
    )

    op.create_table(
        "support_notification_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("support_notifications.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("channel", sa.String(16), server_default="unassigned", nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="ready", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.CheckConstraint(
            "status in ('ready','delivered','failed','cancelled')",
            name="ck_support_notification_outbox_status",
        ),
    )
    op.create_index(
        "ix_support_notification_outbox_status_time",
        "support_notification_outbox",
        ["status", "available_at"],
    )

    for table in (
        "support_notifications",
        "support_notification_reads",
        "support_notification_outbox",
    ):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute(
        """
        CREATE POLICY support_notifications_owner_access ON public.support_notifications
        FOR ALL TO authenticated USING (
            private.has_school_role(school_id, ARRAY['owner']::text[])
        ) WITH CHECK (
            private.has_school_role(school_id, ARRAY['owner']::text[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY support_notification_reads_owner_access ON public.support_notification_reads
        FOR ALL TO authenticated USING (
            EXISTS (SELECT 1 FROM public.support_notifications n
                    WHERE n.id = notification_id
                    AND private.has_school_role(n.school_id, ARRAY['owner']::text[]))
        ) WITH CHECK (
            EXISTS (SELECT 1 FROM public.support_notifications n
                    WHERE n.id = notification_id
                    AND private.has_school_role(n.school_id, ARRAY['owner']::text[]))
        )
        """
    )
    op.execute(
        """
        CREATE POLICY support_notification_outbox_owner_access ON public.support_notification_outbox
        FOR ALL TO authenticated USING (
            EXISTS (SELECT 1 FROM public.support_notifications n
                    WHERE n.id = notification_id
                    AND private.has_school_role(n.school_id, ARRAY['owner']::text[]))
        ) WITH CHECK (
            EXISTS (SELECT 1 FROM public.support_notifications n
                    WHERE n.id = notification_id
                    AND private.has_school_role(n.school_id, ARRAY['owner']::text[]))
        )
        """
    )


def downgrade() -> None:
    op.drop_table("support_notification_outbox")
    op.drop_table("support_notification_reads")
    op.drop_table("support_notifications")
    op.drop_index("ix_support_attestations_submitted_by_user_id", table_name="support_attestations")
    op.drop_index("ix_support_attestations_school_status", table_name="support_attestations")
    op.drop_constraint("ck_support_attestations_status", "support_attestations", type_="check")
    for column in (
        "rejection_reason",
        "reviewed_at",
        "reviewed_by",
        "submitted_at",
        "submitted_by",
        "submitted_by_role",
        "submitted_by_user_id",
        "status",
        "redacted_statement",
    ):
        op.drop_column("support_attestations", column)
