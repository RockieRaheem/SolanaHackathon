"""Add Solana destinations and provider-neutral settlement evidence.

Revision ID: b6f4d9a2c810
Revises: a3d8e71c5f20
Create Date: 2026-11-06 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6f4d9a2c810"
down_revision: str | None = "a3d8e71c5f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.push_deliveries') IS NOT NULL
             AND to_regclass('public.legacy_firebase_push_deliveries_archive') IS NULL THEN
            ALTER TABLE public.push_deliveries
              RENAME TO legacy_firebase_push_deliveries_archive;
          END IF;
          IF to_regclass('public.push_installations') IS NOT NULL
             AND to_regclass('public.legacy_firebase_push_installations_archive') IS NULL THEN
            ALTER TABLE public.push_installations
              RENAME TO legacy_firebase_push_installations_archive;
          END IF;
          IF to_regclass('public.identity_provider_accounts') IS NOT NULL
             AND to_regclass('public.legacy_firebase_identity_accounts_archive') IS NULL THEN
            ALTER TABLE public.identity_provider_accounts
              RENAME TO legacy_firebase_identity_accounts_archive;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE archived_table text;
        BEGIN
          FOREACH archived_table IN ARRAY ARRAY[
            'legacy_firebase_push_deliveries_archive',
            'legacy_firebase_push_installations_archive',
            'legacy_firebase_identity_accounts_archive'
          ] LOOP
            IF to_regclass('public.' || archived_table) IS NOT NULL THEN
              EXECUTE format(
                'REVOKE ALL ON TABLE public.%I FROM anon, authenticated',
                archived_table
              );
            END IF;
          END LOOP;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'support_referrals'
              AND column_name = 'gemini_processing'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'support_referrals'
              AND column_name = 'gemma_processing'
          ) THEN
            ALTER TABLE public.support_referrals
              RENAME COLUMN gemini_processing TO gemma_processing;
          END IF;
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'support_consents'
              AND column_name = 'gemini_processing'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'support_consents'
              AND column_name = 'gemma_processing'
          ) THEN
            ALTER TABLE public.support_consents
              RENAME COLUMN gemini_processing TO gemma_processing;
          END IF;
        END $$;
        """
    )
    op.rename_table("stellar_anchors", "settlement_anchors")
    op.execute("UPDATE settlement_anchors SET network = 'offchain' WHERE network = 'testnet'")
    op.alter_column(
        "settlement_anchors",
        "network",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
        server_default="offchain",
    )
    op.alter_column(
        "settlement_anchors",
        "transaction_hash",
        new_column_name="transaction_signature",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
    op.alter_column(
        "settlement_anchors",
        "ledger_number",
        new_column_name="confirmation_slot",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_stellar_anchors_transaction_hash'
              AND conrelid = 'public.settlement_anchors'::regclass
          ) THEN
            ALTER TABLE public.settlement_anchors
              RENAME CONSTRAINT uq_stellar_anchors_transaction_hash
              TO uq_settlement_anchors_transaction_signature;
          END IF;
        END $$;
        """
    )
    op.drop_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        "channel in ('schoolpay','bank','mobile_money','solana')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM support_payment_destinations WHERE channel = 'solana'")
    op.drop_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_support_payment_destinations_channel",
        "support_payment_destinations",
        "channel in ('schoolpay','bank','mobile_money')",
    )
    op.alter_column(
        "settlement_anchors",
        "confirmation_slot",
        new_column_name="ledger_number",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    op.execute(
        "UPDATE settlement_anchors SET transaction_signature = NULL, "
        "network = 'testnet' WHERE network = 'solana-devnet'"
    )
    op.alter_column(
        "settlement_anchors",
        "transaction_signature",
        new_column_name="transaction_hash",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "settlement_anchors",
        "network",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
        server_default="testnet",
    )
    op.rename_table("settlement_anchors", "stellar_anchors")
