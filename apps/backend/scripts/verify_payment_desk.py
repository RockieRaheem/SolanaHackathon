from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "b72c41e9a603"
CONTROL_TABLES = (
    "payment_receipt_sequences",
    "payment_channels",
    "payment_receipt_reissues",
)
REQUIRED_INDEXES = {
    "ix_payments_school_received",
    "ix_payments_original",
    "ix_payment_allocations_payment",
    "ix_payment_allocations_student",
    "ix_payment_channels_school_active",
    "ix_payment_receipt_reissues_payment_time",
}
REQUIRED_TRIGGERS = {
    "payments_immutable",
    "payment_allocations_immutable",
    "payment_reissues_immutable",
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
                select count(*)
                from information_schema.role_table_grants
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
                    where schemaname = 'public'
                      and tablename in (
                        'payments', 'payment_allocations', 'payment_channels',
                        'payment_receipt_reissues'
                      )
                    """
                )
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
                      and relation.relname in (
                        'payments', 'payment_allocations', 'payment_receipt_reissues'
                      )
                    """
                )
            )
        )
        required_constraints = connection.scalar(
            text(
                """
                select count(*) from pg_constraint
                where conname in (
                    'uq_payment_correction_key',
                    'ck_payments_transaction_type',
                    'ck_payments_amount_direction',
                    'ck_payment_allocations_type',
                    'ck_payment_allocations_amount'
                )
                """
            )
        )
        missing_standard_channels = connection.scalar(
            text(
                """
                select count(*)
                from schools school
                cross join (values ('cash'), ('bank'), ('mobile_money'), ('schoolpay')) preset(code)
                where not exists (
                    select 1 from payment_channels channel
                    where channel.school_id = school.id and channel.code = preset.code
                )
                """
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(CONTROL_TABLES), "Payment control table RLS is incomplete"
    assert exposed_grants == 0, "Payment control tables are exposed through the Data API"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert required_constraints == 5, "Payment integrity constraints are incomplete"
    assert missing_standard_channels == 0, "A current school is missing standard channels"
    print(
        "Payment desk verified: migration head, channels, RLS, grants, indexes, "
        "constraints and immutable financial history passed"
    )


if __name__ == "__main__":
    main()
