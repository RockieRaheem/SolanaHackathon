"""Add identified campaign consent and offline evidence.

Revision ID: d1a6c3f8b902
Revises: c7e5a1d9f204
Create Date: 2026-11-08 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a6c3f8b902"
down_revision: str | None = "c7e5a1d9f204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "support_referrals",
        sa.Column(
            "public_identity_consent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "support_consents",
        sa.Column(
            "public_identity_consent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("support_consents", sa.Column("evidence_filename", sa.String(160)))
    op.add_column("support_consents", sa.Column("evidence_mime_type", sa.String(80)))
    op.add_column("support_consents", sa.Column("evidence_content", sa.LargeBinary()))
    op.add_column("support_consents", sa.Column("evidence_hash", sa.String(64)))
    op.add_column("support_consents", sa.Column("evidence_note", sa.String(500)))


def downgrade() -> None:
    op.drop_column("support_consents", "evidence_note")
    op.drop_column("support_consents", "evidence_hash")
    op.drop_column("support_consents", "evidence_content")
    op.drop_column("support_consents", "evidence_mime_type")
    op.drop_column("support_consents", "evidence_filename")
    op.drop_column("support_consents", "public_identity_consent")
    op.drop_column("support_referrals", "public_identity_consent")
