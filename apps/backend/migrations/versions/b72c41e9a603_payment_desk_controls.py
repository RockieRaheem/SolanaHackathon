"""add canonical payment desk controls

Revision ID: b72c41e9a603
Revises: a91d38c7e5f2
Create Date: 2026-10-22 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b72c41e9a603"
down_revision: str | None = "a91d38c7e5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("transaction_type", sa.String(16), server_default="receipt", nullable=False),
    )
    op.add_column("payments", sa.Column("original_payment_id", sa.Uuid()))
    op.add_column("payments", sa.Column("correction_reason", sa.String(500)))
    op.add_column("payments", sa.Column("idempotency_key", sa.String(80)))
    op.add_column("payments", sa.Column("created_by", sa.String(120)))
    op.create_foreign_key(
        "fk_payments_original_payment_id",
        "payments",
        "payments",
        ["original_payment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute("UPDATE payments SET transaction_type = 'reversal' WHERE amount < 0")
    op.create_check_constraint(
        "ck_payments_transaction_type",
        "payments",
        "transaction_type in ('receipt','reversal','refund')",
    )
    op.create_check_constraint(
        "ck_payments_amount_direction",
        "payments",
        "(transaction_type = 'receipt' and amount > 0) or "
        "(transaction_type in ('reversal','refund') and amount < 0)",
    )
    op.create_index("ix_payments_original", "payments", ["original_payment_id"])
    op.create_unique_constraint(
        "uq_payment_correction_key",
        "payments",
        ["original_payment_id", "idempotency_key"],
    )

    op.add_column(
        "payment_allocations",
        sa.Column("allocation_type", sa.String(16), server_default="fees", nullable=False),
    )
    op.execute(
        "UPDATE payment_allocations SET allocation_type = 'requirement' "
        "WHERE requirement_assignment_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_payment_allocations_type",
        "payment_allocations",
        "allocation_type in ('fees','requirement','unallocated')",
    )
    op.create_check_constraint(
        "ck_payment_allocations_amount", "payment_allocations", "amount <> 0"
    )
    op.create_index(
        "ix_payment_allocations_student", "payment_allocations", ["student_id"]
    )

    op.create_table(
        "payment_receipt_sequences",
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("next_number", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "next_number > 0", name="ck_payment_receipt_sequences_positive"
        ),
    )
    op.create_table(
        "payment_channels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("channel_type", sa.String(24), nullable=False),
        sa.Column("requires_reference", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("school_id", "code", name="uq_payment_channels_school_code"),
        sa.CheckConstraint(
            "channel_type in ('cash','bank','mobile_money','schoolpay','card','other')",
            name="ck_payment_channels_type",
        ),
    )
    op.create_index("ix_payment_channels_school_id", "payment_channels", ["school_id"])
    op.create_index(
        "ix_payment_channels_school_active", "payment_channels", ["school_id", "is_active"]
    )
    op.create_table(
        "payment_receipt_reissues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            sa.Uuid(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("reissued_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_payment_receipt_reissues_school_id", "payment_receipt_reissues", ["school_id"]
    )
    op.create_index(
        "ix_payment_receipt_reissues_payment_id", "payment_receipt_reissues", ["payment_id"]
    )
    op.create_index(
        "ix_payment_receipt_reissues_payment_time",
        "payment_receipt_reissues",
        ["payment_id", "created_at"],
    )
    op.execute(
        """
        INSERT INTO payment_channels
            (id, school_id, code, label, channel_type, requires_reference, is_active, created_by)
        SELECT gen_random_uuid(), school.id, preset.code, preset.label, preset.channel_type,
               preset.requires_reference, true, 'migration'
        FROM schools school
        CROSS JOIN (VALUES
            ('cash', 'Cash', 'cash', false),
            ('bank', 'Bank deposit / transfer', 'bank', true),
            ('mobile_money', 'Mobile Money', 'mobile_money', true),
            ('schoolpay', 'SchoolPay', 'schoolpay', true),
            ('card', 'Card', 'card', true)
        ) AS preset(code, label, channel_type, requires_reference)
        """
    )
    for table in (
        "payment_receipt_sequences",
        "payment_channels",
        "payment_receipt_reissues",
    ):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_access ON public.{table}
            FOR ALL TO authenticated
            USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
            WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
            """
        )

    op.execute(
        """
        CREATE FUNCTION private.protect_payment_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Financial history cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.school_id IS DISTINCT FROM OLD.school_id
               OR NEW.period_id IS DISTINCT FROM OLD.period_id
               OR NEW.receipt_no IS DISTINCT FROM OLD.receipt_no
               OR NEW.external_reference IS DISTINCT FROM OLD.external_reference
               OR NEW.payer_name IS DISTINCT FROM OLD.payer_name
               OR NEW.note IS DISTINCT FROM OLD.note
               OR NEW.channel IS DISTINCT FROM OLD.channel
               OR NEW.amount IS DISTINCT FROM OLD.amount
               OR NEW.currency IS DISTINCT FROM OLD.currency
               OR NEW.transaction_type IS DISTINCT FROM OLD.transaction_type
               OR NEW.original_payment_id IS DISTINCT FROM OLD.original_payment_id
               OR NEW.correction_reason IS DISTINCT FROM OLD.correction_reason
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
                RAISE EXCEPTION 'Financial history is immutable; post a correction instead';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER payments_immutable
        BEFORE UPDATE OR DELETE ON public.payments
        FOR EACH ROW EXECUTE FUNCTION private.protect_payment_history();

        CREATE FUNCTION private.reject_financial_history_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Financial history is immutable; post a correction instead';
        END;
        $$;
        CREATE TRIGGER payment_allocations_immutable
        BEFORE UPDATE OR DELETE ON public.payment_allocations
        FOR EACH ROW EXECUTE FUNCTION private.reject_financial_history_change();
        CREATE TRIGGER payment_reissues_immutable
        BEFORE UPDATE OR DELETE ON public.payment_receipt_reissues
        FOR EACH ROW EXECUTE FUNCTION private.reject_financial_history_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS payment_reissues_immutable ON payment_receipt_reissues")
    op.execute("DROP TRIGGER IF EXISTS payment_allocations_immutable ON payment_allocations")
    op.execute("DROP TRIGGER IF EXISTS payments_immutable ON payments")
    op.execute("DROP FUNCTION IF EXISTS private.reject_financial_history_change()")
    op.execute("DROP FUNCTION IF EXISTS private.protect_payment_history()")
    op.drop_table("payment_receipt_reissues")
    op.drop_table("payment_channels")
    op.drop_table("payment_receipt_sequences")
    op.drop_index("ix_payment_allocations_student", table_name="payment_allocations")
    op.drop_constraint(
        "ck_payment_allocations_amount", "payment_allocations", type_="check"
    )
    op.drop_constraint("ck_payment_allocations_type", "payment_allocations", type_="check")
    op.drop_column("payment_allocations", "allocation_type")
    op.drop_index("ix_payments_original", table_name="payments")
    op.drop_constraint("uq_payment_correction_key", "payments", type_="unique")
    op.drop_constraint("ck_payments_amount_direction", "payments", type_="check")
    op.drop_constraint("ck_payments_transaction_type", "payments", type_="check")
    op.drop_constraint("fk_payments_original_payment_id", "payments", type_="foreignkey")
    op.drop_column("payments", "created_by")
    op.drop_column("payments", "correction_reason")
    op.drop_column("payments", "idempotency_key")
    op.drop_column("payments", "original_payment_id")
    op.drop_column("payments", "transaction_type")
