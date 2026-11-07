"""Add verified Solana donation intents.

Revision ID: c7e5a1d9f204
Revises: b6f4d9a2c810
Create Date: 2026-11-07 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e5a1d9f204"
down_revision: str | None = "b6f4d9a2c810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solana_donation_intents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pledge_id",
            sa.Uuid(),
            sa.ForeignKey("support_pledges.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sender_address", sa.String(64)),
        sa.Column("recipient_address", sa.String(64), nullable=False),
        sa.Column("expected_lamports", sa.BigInteger(), nullable=False),
        sa.Column("quote_ugx_per_sol", sa.Numeric(18, 2), nullable=False),
        sa.Column("memo", sa.String(100), nullable=False),
        sa.Column("cluster", sa.String(24), nullable=False, server_default="devnet"),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("transaction_signature", sa.String(128)),
        sa.Column("confirmation_slot", sa.BigInteger()),
        sa.Column("transaction_block_time", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expected_lamports > 0", name="ck_solana_intents_lamports"),
        sa.CheckConstraint(
            "status in ('created','confirmed','expired')", name="ck_solana_intents_status"
        ),
        sa.UniqueConstraint("pledge_id", name="uq_solana_intents_pledge_id"),
        sa.UniqueConstraint("memo", name="uq_solana_intents_memo"),
        sa.UniqueConstraint(
            "transaction_signature", name="uq_solana_intents_transaction_signature"
        ),
    )
    op.create_index(
        "ix_solana_intents_pledge_id", "solana_donation_intents", ["pledge_id"], unique=True
    )
    op.create_index(
        "ix_solana_intents_status_expiry", "solana_donation_intents", ["status", "expires_at"]
    )
    op.execute("ALTER TABLE public.solana_donation_intents ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE public.solana_donation_intents FROM anon, authenticated")
    op.execute(
        """
        CREATE FUNCTION private.protect_confirmed_solana_intent()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
          IF OLD.status = 'confirmed' THEN
            RAISE EXCEPTION 'Confirmed Solana evidence is immutable';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END; $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION private.protect_confirmed_solana_intent() "
        "FROM PUBLIC, anon, authenticated"
    )
    op.execute(
        "CREATE TRIGGER solana_intents_immutable BEFORE UPDATE OR DELETE "
        "ON public.solana_donation_intents "
        "FOR EACH ROW EXECUTE FUNCTION private.protect_confirmed_solana_intent()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS solana_intents_immutable ON public.solana_donation_intents")
    op.execute("DROP FUNCTION IF EXISTS private.protect_confirmed_solana_intent()")
    op.drop_index("ix_solana_intents_status_expiry", table_name="solana_donation_intents")
    op.drop_index("ix_solana_intents_pledge_id", table_name="solana_donation_intents")
    op.drop_table("solana_donation_intents")
