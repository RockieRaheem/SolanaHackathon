from sqlalchemy import text

from harambeeone_api.database import get_engine

TABLES = (
    "integration_clients",
    "integration_webhook_subscriptions",
    "integration_outbox_events",
    "integration_deliveries",
    "integration_exchange_logs",
    "integration_import_batches",
)
REQUIRED_INDEXES = {
    "uq_integration_clients_school_name",
    "uq_integration_webhooks_url",
    "uq_integration_delivery_event_hook",
    "uq_integration_import_client_key",
    "ix_integration_deliveries_school_status",
    "ix_integration_exchange_school_created",
    "ix_integration_import_school_status",
}


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rls_tables = set(
            connection.execute(
                text(
                    """
                    SELECT table_record.relname
                    FROM pg_class AS table_record
                    JOIN pg_namespace AS schema_record
                      ON schema_record.oid = table_record.relnamespace
                    WHERE schema_record.nspname = 'public'
                      AND table_record.relrowsecurity
                      AND table_record.relname = ANY(:tables)
                    """
                ),
                {"tables": list(TABLES)},
            ).scalars()
        )
        exposed_grants = connection.execute(
            text(
                """
                SELECT count(*)
                FROM information_schema.role_table_grants
                WHERE table_schema = 'public'
                  AND table_name = ANY(:tables)
                  AND grantee IN ('anon', 'authenticated')
                """
            ),
            {"tables": list(TABLES)},
        ).scalar_one()
        owner_policies = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = ANY(:tables)
                  AND policyname LIKE '%_owner_access'
                """
            ),
            {"tables": list(TABLES)},
        ).scalar_one()
        indexes = set(
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = ANY(:tables)
                    """
                ),
                {"tables": list(TABLES)},
            ).scalars()
        )

    assert revision == "e84a1f03c9b2", f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from: {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Integration tables are exposed through the Data API"
    assert owner_policies == len(TABLES), "Owner policies are incomplete"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    print(
        "External exchange verified: migration head, RLS, revoked Data API grants, "
        "owner policies, uniqueness and delivery indexes passed"
    )


if __name__ == "__main__":
    main()
