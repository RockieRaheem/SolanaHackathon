from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "c83d7a2f14e6"
CONTROL_TABLES = (
    "statement_imports",
    "statement_transactions",
    "cashier_collection_batches",
    "cashier_batch_payments",
)
REQUIRED_INDEXES = {
    "ix_statement_imports_school_period",
    "ix_statement_transactions_school_period_status",
    "ix_cashier_batches_school_period_status",
    "ix_cashier_batch_payments_batch",
    "uq_cashier_batch_payment",
}
REQUIRED_TRIGGERS = {
    "statement_import_source_immutable",
    "statement_transaction_source_immutable",
    "cashier_batch_identity_immutable",
    "cashier_batch_payments_immutable",
}


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.scalar(text("select version_num from alembic_version"))
        rls_tables = set(
            connection.scalars(
                text(
                    """
                    select relation.relname
                    from pg_class relation
                    join pg_namespace namespace on namespace.oid = relation.relnamespace
                    where namespace.nspname = 'public'
                      and relation.relrowsecurity
                      and relation.relname = any(:tables)
                    """
                ),
                {"tables": list(CONTROL_TABLES)},
            )
        )
        exposed_grants = connection.scalar(
            text(
                """
                select count(*) from information_schema.role_table_grants
                where table_schema = 'public'
                  and table_name = any(:tables)
                  and grantee in ('anon', 'authenticated')
                """
            ),
            {"tables": list(CONTROL_TABLES)},
        )
        indexes = set(
            connection.scalars(
                text(
                    """
                    select indexname from pg_indexes
                    where schemaname = 'public' and tablename = any(:tables)
                    """
                ),
                {"tables": list(CONTROL_TABLES)},
            )
        )
        triggers = set(
            connection.scalars(
                text(
                    """
                    select trigger_record.tgname
                    from pg_trigger trigger_record
                    join pg_class relation on relation.oid = trigger_record.tgrelid
                    where not trigger_record.tgisinternal
                      and relation.relname = any(:tables)
                    """
                ),
                {"tables": list(CONTROL_TABLES)},
            )
        )
        constraints = set(
            connection.scalars(
                text(
                    """
                    select conname from pg_constraint
                    where conname in (
                      'uq_statement_import_content', 'uq_statement_import_key',
                      'ck_statement_transactions_status',
                      'ck_statement_transactions_channel', 'uq_cashier_batch_day',
                      'uq_cashier_batch_payment', 'ck_cashier_batches_status'
                    )
                    """
                )
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(CONTROL_TABLES), f"RLS missing from {set(CONTROL_TABLES)-rls_tables}"
    assert exposed_grants == 0, "Reconciliation controls are exposed through the Data API"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES-indexes}"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS-triggers}"
    assert len(constraints) == 7, "Reconciliation integrity constraints are incomplete"
    print(
        "Reconciliation verified: migration head, RLS, grants, duplicate controls, "
        "cash-up indexes and immutable source evidence passed"
    )


if __name__ == "__main__":
    main()
