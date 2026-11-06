from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "f6a91c42d7e0"
TABLES = (
    "support_notifications",
    "support_notification_reads",
    "support_notification_outbox",
)
REQUIRED_INDEXES = {
    "ix_support_notifications_school_time",
    "ix_support_notifications_user_time",
    "ix_support_notification_reads_user",
    "ix_support_notification_outbox_status_time",
    "ix_support_attestations_school_status",
}


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rls_tables = set(
            connection.execute(
                text(
                    """
                    SELECT c.relname FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relrowsecurity
                      AND c.relname = ANY(:tables)
                    """
                ),
                {"tables": list(TABLES)},
            ).scalars()
        )
        grants = connection.execute(
            text(
                """
                SELECT count(*) FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = ANY(:tables)
                  AND grantee IN ('anon','authenticated')
                """
            ),
            {"tables": list(TABLES)},
        ).scalar_one()
        policies = connection.execute(
            text(
                """
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'public' AND tablename = ANY(:tables)
                  AND policyname LIKE '%_owner_access'
                """
            ),
            {"tables": list(TABLES)},
        ).scalar_one()
        indexes = set(
            connection.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND (tablename = ANY(:tables) OR tablename = 'support_attestations')
                    """
                ),
                {"tables": list(TABLES)},
            ).scalars()
        )
        invalid_outcomes = connection.execute(
            text(
                """
                SELECT count(*) FROM support_attestations
                WHERE status IS NULL OR submitted_by IS NULL OR submitted_at IS NULL
                   OR (status = 'approved' AND redacted_statement IS NULL)
                """
            )
        ).scalar_one()

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from: {set(TABLES) - rls_tables}"
    assert grants == 0, "Notification tables are exposed through the Data API"
    assert policies == len(TABLES), "Owner policies are incomplete"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert invalid_outcomes == 0, "Outcome evidence migration left invalid rows"
    print(
        "Support S5 verified: migration head, RLS, revoked grants, policies, "
        "delivery indexes and outcome backfill passed"
    )


if __name__ == "__main__":
    main()
