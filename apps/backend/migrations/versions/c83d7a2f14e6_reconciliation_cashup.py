"""complete reconciliation and cashier cash-up controls

Revision ID: c83d7a2f14e6
Revises: b72c41e9a603
Create Date: 2026-10-23 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c83d7a2f14e6"
down_revision: str | None = "b72c41e9a603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("statement_imports", sa.Column("period_id", sa.Uuid()))
    op.add_column("statement_imports", sa.Column("source_type", sa.String(24)))
    op.add_column("statement_imports", sa.Column("content_hash", sa.String(64)))
    op.add_column("statement_imports", sa.Column("idempotency_key", sa.String(80)))
    op.add_column("statement_imports", sa.Column("total_amount", sa.Numeric(18, 2)))
    op.add_column("statement_imports", sa.Column("imported_by", sa.String(120)))
    op.create_foreign_key(
        "fk_statement_imports_period",
        "statement_imports",
        "academic_periods",
        ["period_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column("statement_transactions", sa.Column("period_id", sa.Uuid()))
    op.add_column("statement_transactions", sa.Column("channel", sa.String(24)))
    op.add_column("statement_transactions", sa.Column("match_reason", sa.String(240)))
    op.add_column("statement_transactions", sa.Column("review_reason", sa.String(500)))
    op.add_column("statement_transactions", sa.Column("reviewed_by", sa.String(120)))
    op.add_column("statement_transactions", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("statement_transactions", sa.Column("reversal_payment_id", sa.Uuid()))
    op.add_column(
        "statement_transactions",
        sa.Column(
            "payment_created_by_reconciliation",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_statement_transactions_period",
        "statement_transactions",
        "academic_periods",
        ["period_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_statement_transactions_reversal",
        "statement_transactions",
        "payments",
        ["reversal_payment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_statement_transactions_reversal", "statement_transactions", ["reversal_payment_id"]
    )
    op.execute(
        """
        UPDATE statement_transactions transaction
        SET period_id = COALESCE(
                (SELECT payment.period_id FROM payments payment
                 WHERE payment.id = transaction.payment_id),
                (SELECT period.id FROM academic_periods period
                 WHERE period.school_id = transaction.school_id
                 ORDER BY (period.status IN ('open','closing')) DESC,
                          period.opening_date DESC LIMIT 1)
            ),
            channel = 'bank',
            match_reason = CASE WHEN transaction.status = 'suggested'
                                THEN 'Legacy exact learner reference match' END
        """
    )
    op.execute(
        """
        UPDATE statement_imports import_record
        SET period_id = COALESCE(
                (SELECT transaction.period_id FROM statement_transactions transaction
                 WHERE transaction.import_id = import_record.id LIMIT 1),
                (SELECT period.id FROM academic_periods period
                 WHERE period.school_id = import_record.school_id
                 ORDER BY (period.status IN ('open','closing')) DESC,
                          period.opening_date DESC LIMIT 1)
            ),
            source_type = 'bank',
            content_hash = encode(digest(import_record.id::text, 'sha256'), 'hex'),
            idempotency_key = 'legacy-' || replace(import_record.id::text, '-', ''),
            total_amount = COALESCE(
                (SELECT sum(transaction.amount) FROM statement_transactions transaction
                 WHERE transaction.import_id = import_record.id), 0
            ),
            imported_by = 'migration'
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM statement_imports WHERE period_id IS NULL)
             OR EXISTS (SELECT 1 FROM statement_transactions WHERE period_id IS NULL) THEN
            RAISE EXCEPTION 'Existing reconciliation records require an academic period';
          END IF;
        END $$
        """
    )
    for table, columns in (
        (
            "statement_imports",
            (
                "period_id",
                "source_type",
                "content_hash",
                "idempotency_key",
                "total_amount",
                "imported_by",
            ),
        ),
        ("statement_transactions", ("period_id", "channel")),
    ):
        for column in columns:
            op.alter_column(table, column, nullable=False)

    op.create_unique_constraint(
        "uq_statement_import_content", "statement_imports", ["school_id", "content_hash"]
    )
    op.create_unique_constraint(
        "uq_statement_import_key", "statement_imports", ["school_id", "idempotency_key"]
    )
    op.create_check_constraint(
        "ck_statement_imports_source_type",
        "statement_imports",
        "source_type in ('bank','mobile_money','schoolpay')",
    )
    op.create_index(
        "ix_statement_imports_school_period",
        "statement_imports",
        ["school_id", "period_id", "imported_at"],
    )
    op.create_check_constraint(
        "ck_statement_transactions_status",
        "statement_transactions",
        "status in ('suggested','unmatched','reconciled','rejected','unidentified','reversed')",
    )
    op.create_check_constraint(
        "ck_statement_transactions_channel",
        "statement_transactions",
        "channel in ('bank','mobile_money','schoolpay')",
    )
    op.create_index(
        "ix_statement_transactions_school_period_status",
        "statement_transactions",
        ["school_id", "period_id", "status", "transaction_date"],
    )

    op.create_table(
        "cashier_collection_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "period_id",
            sa.Uuid(),
            sa.ForeignKey("academic_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("cashier_actor", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("expected_cash", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("counted_cash", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("variance", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("deposit_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("deposit_reference", sa.String(100)),
        sa.Column("cashier_note", sa.String(500)),
        sa.Column("supervisor_note", sa.String(500)),
        sa.Column("idempotency_key", sa.String(80)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("signed_off_by", sa.String(120)),
        sa.Column("signed_off_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "school_id",
            "period_id",
            "cashier_actor",
            "business_date",
            name="uq_cashier_batch_day",
        ),
        sa.CheckConstraint(
            "status in ('open','submitted','returned','signed_off')",
            name="ck_cashier_batches_status",
        ),
        sa.CheckConstraint("expected_cash >= 0", name="ck_cashier_batches_expected"),
        sa.CheckConstraint("counted_cash >= 0", name="ck_cashier_batches_counted"),
        sa.CheckConstraint("deposit_amount >= 0", name="ck_cashier_batches_deposit"),
    )
    op.create_index(
        "ix_cashier_collection_batches_school_id", "cashier_collection_batches", ["school_id"]
    )
    op.create_index(
        "ix_cashier_collection_batches_period_id", "cashier_collection_batches", ["period_id"]
    )
    op.create_index(
        "ix_cashier_batches_school_period_status",
        "cashier_collection_batches",
        ["school_id", "period_id", "status", "business_date"],
    )
    op.create_table(
        "cashier_batch_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("cashier_collection_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            sa.Uuid(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("payment_id", name="uq_cashier_batch_payment"),
    )
    op.create_index("ix_cashier_batch_payments_batch", "cashier_batch_payments", ["batch_id"])

    for table in ("cashier_collection_batches", "cashier_batch_payments"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated")
    op.execute(
        """
        CREATE POLICY cashier_batches_owner_access ON public.cashier_collection_batches
        FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]));
        CREATE POLICY cashier_batch_payments_owner_access ON public.cashier_batch_payments
        FOR ALL TO authenticated
        USING (EXISTS (
          SELECT 1 FROM cashier_collection_batches batch
          WHERE batch.id = batch_id
            AND private.has_school_role(batch.school_id, ARRAY['owner']::text[])
        ))
        WITH CHECK (EXISTS (
          SELECT 1 FROM cashier_collection_batches batch
          WHERE batch.id = batch_id
            AND private.has_school_role(batch.school_id, ARRAY['owner']::text[])
        ));
        """
    )
    op.execute(
        """
        CREATE FUNCTION private.protect_statement_import_source() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Statement imports cannot be deleted'; END IF;
          IF NEW.id IS DISTINCT FROM OLD.id OR NEW.school_id IS DISTINCT FROM OLD.school_id
             OR NEW.period_id IS DISTINCT FROM OLD.period_id
             OR NEW.file_name IS DISTINCT FROM OLD.file_name
             OR NEW.source_type IS DISTINCT FROM OLD.source_type
             OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
             OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
             OR NEW.row_count IS DISTINCT FROM OLD.row_count
             OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
             OR NEW.imported_by IS DISTINCT FROM OLD.imported_by
             OR NEW.imported_at IS DISTINCT FROM OLD.imported_at THEN
            RAISE EXCEPTION 'Statement source evidence is immutable';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER statement_import_source_immutable
        BEFORE UPDATE OR DELETE ON public.statement_imports
        FOR EACH ROW EXECUTE FUNCTION private.protect_statement_import_source();

        CREATE FUNCTION private.protect_statement_transaction_source() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Statement transactions cannot be deleted';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id OR NEW.import_id IS DISTINCT FROM OLD.import_id
             OR NEW.school_id IS DISTINCT FROM OLD.school_id
             OR NEW.period_id IS DISTINCT FROM OLD.period_id
             OR NEW.transaction_date IS DISTINCT FROM OLD.transaction_date
             OR NEW.source_reference IS DISTINCT FROM OLD.source_reference
             OR NEW.description IS DISTINCT FROM OLD.description
             OR NEW.amount IS DISTINCT FROM OLD.amount
             OR NEW.channel IS DISTINCT FROM OLD.channel THEN
            RAISE EXCEPTION 'Statement transaction source evidence is immutable';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER statement_transaction_source_immutable
        BEFORE UPDATE OR DELETE ON public.statement_transactions
        FOR EACH ROW EXECUTE FUNCTION private.protect_statement_transaction_source();

        CREATE FUNCTION private.protect_cash_batch_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Cash-up history cannot be deleted'; END IF;
          IF NEW.id IS DISTINCT FROM OLD.id OR NEW.school_id IS DISTINCT FROM OLD.school_id
             OR NEW.period_id IS DISTINCT FROM OLD.period_id
             OR NEW.business_date IS DISTINCT FROM OLD.business_date
             OR NEW.cashier_actor IS DISTINCT FROM OLD.cashier_actor
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'Cash-up identity is immutable';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER cashier_batch_identity_immutable
        BEFORE UPDATE OR DELETE ON public.cashier_collection_batches
        FOR EACH ROW EXECUTE FUNCTION private.protect_cash_batch_identity();

        CREATE FUNCTION private.protect_cash_batch_payments() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'Cash-up payment evidence is immutable';
        END; $$;
        CREATE TRIGGER cashier_batch_payments_immutable
        BEFORE UPDATE OR DELETE ON public.cashier_batch_payments
        FOR EACH ROW EXECUTE FUNCTION private.protect_cash_batch_payments();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS cashier_batch_identity_immutable ON cashier_collection_batches"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS statement_transaction_source_immutable ON statement_transactions"
    )
    op.execute("DROP TRIGGER IF EXISTS statement_import_source_immutable ON statement_imports")
    op.execute("DROP FUNCTION IF EXISTS private.protect_cash_batch_identity()")
    op.execute("DROP FUNCTION IF EXISTS private.protect_statement_transaction_source()")
    op.execute("DROP FUNCTION IF EXISTS private.protect_statement_import_source()")
    op.execute("DROP TRIGGER IF EXISTS cashier_batch_payments_immutable ON cashier_batch_payments")
    op.execute("DROP FUNCTION IF EXISTS private.protect_cash_batch_payments()")
    op.drop_table("cashier_batch_payments")
    op.drop_table("cashier_collection_batches")
    op.drop_index(
        "ix_statement_transactions_school_period_status", table_name="statement_transactions"
    )
    op.drop_constraint("ck_statement_transactions_channel", "statement_transactions", type_="check")
    op.drop_constraint("ck_statement_transactions_status", "statement_transactions", type_="check")
    op.drop_constraint(
        "uq_statement_transactions_reversal", "statement_transactions", type_="unique"
    )
    op.drop_constraint(
        "fk_statement_transactions_reversal", "statement_transactions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_statement_transactions_period", "statement_transactions", type_="foreignkey"
    )
    for column in (
        "payment_created_by_reconciliation",
        "reversal_payment_id",
        "reviewed_at",
        "reviewed_by",
        "review_reason",
        "match_reason",
        "channel",
        "period_id",
    ):
        op.drop_column("statement_transactions", column)
    op.drop_index("ix_statement_imports_school_period", table_name="statement_imports")
    op.drop_constraint("ck_statement_imports_source_type", "statement_imports", type_="check")
    op.drop_constraint("uq_statement_import_key", "statement_imports", type_="unique")
    op.drop_constraint("uq_statement_import_content", "statement_imports", type_="unique")
    op.drop_constraint("fk_statement_imports_period", "statement_imports", type_="foreignkey")
    for column in (
        "imported_by",
        "total_amount",
        "idempotency_key",
        "content_hash",
        "source_type",
        "period_id",
    ):
        op.drop_column("statement_imports", column)
