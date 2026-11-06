from sqlalchemy import text

from harambeeone_api.database import get_engine


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.scalar(text("select version_num from alembic_version"))
        assert revision == "7ac4d92e1b63", f"Unexpected migration revision: {revision}"
        tables = set(
            connection.scalars(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema='public'"
                )
            )
        )
        required_tables = {
            "support_payment_destinations",
            "support_receipt_sequences",
            "support_receipt_reissues",
        }
        assert required_tables <= tables, f"Missing tables: {required_tables - tables}"
        columns = set(
            connection.scalars(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema='public' and table_name='support_pledges'"
                )
            )
        )
        required_columns = {
            "payment_destination_id",
            "donor_auth_user_id",
            "idempotency_key",
            "rejection_reason",
            "reversed_at",
            "reversed_by",
            "reversal_reason",
            "reversal_payment_id",
        }
        assert required_columns <= columns, f"Missing pledge columns: {required_columns - columns}"
        indexes = set(
            connection.scalars(
                text(
                    "select indexname from pg_indexes where schemaname='public' "
                    "and tablename='support_pledges'"
                )
            )
        )
        assert "uq_support_pledges_case_idempotency" in indexes
        assert "uq_support_pledges_reversal_payment_id" in indexes
        rls_tables = set(
            connection.scalars(
                text(
                    "select relname from pg_class join pg_namespace on "
                    "pg_namespace.oid=pg_class.relnamespace where nspname='public' "
                    "and relrowsecurity and relname in "
                    "('support_payment_destinations','support_receipt_sequences',"
                    "'support_receipt_reissues')"
                )
            )
        )
        assert rls_tables == required_tables, f"RLS missing for: {required_tables - rls_tables}"
        exposed_grants = connection.scalar(
            text(
                "select count(*) from information_schema.role_table_grants "
                "where table_schema='public' and table_name in "
                "('support_payment_destinations','support_receipt_sequences',"
                "'support_receipt_reissues') and grantee in ('anon','authenticated')"
            )
        )
        assert exposed_grants == 0, "Support settlement tables have exposed Data API grants"
        trigger_exists = connection.scalar(
            text(
                "select count(*) from pg_trigger join pg_class on pg_class.oid=tgrelid "
                "where not tgisinternal and relname='support_pledges' "
                "and tgname='protect_verified_support_pledges'"
            )
        )
        assert trigger_exists == 1, "Posted contribution immutability trigger is missing"
    print("Controlled contribution schema, idempotency, RLS and immutability passed.")


if __name__ == "__main__":
    main()
