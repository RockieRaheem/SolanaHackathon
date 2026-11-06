from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "a91d38c7e5f2"
TABLE = "support_assistant_usage"
EXPECTED_COLUMNS = {
    "id",
    "school_id",
    "auth_user_id",
    "persona",
    "task",
    "scope_id",
    "model_name",
    "status",
    "created_at",
    "completed_at",
}
REQUIRED_INDEXES = {
    "ix_support_assistant_usage_school_id",
    "ix_support_assistant_usage_auth_user_id",
    "ix_support_assistant_usage_scope_id",
    "ix_support_assistant_usage_user_time",
    "ix_support_assistant_usage_school_time",
}


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rls_enabled = connection.execute(
            text(
                """
                SELECT c.relrowsecurity FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = :table
                """
            ),
            {"table": TABLE},
        ).scalar_one()
        grants = connection.execute(
            text(
                """
                SELECT count(*) FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = :table
                  AND grantee IN ('anon','authenticated')
                """
            ),
            {"table": TABLE},
        ).scalar_one()
        policies = connection.execute(
            text(
                """
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'public' AND tablename = :table
                  AND policyname = 'support_assistant_usage_owner_access'
                """
            ),
            {"table": TABLE},
        ).scalar_one()
        indexes = set(
            connection.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = :table
                    """
                ),
                {"table": TABLE},
            ).scalars()
        )
        columns = set(
            connection.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table
                    """
                ),
                {"table": TABLE},
            ).scalars()
        )
        check_constraints = connection.execute(
            text(
                """
                SELECT count(*) FROM pg_constraint constraint_record
                JOIN pg_class table_record ON table_record.oid = constraint_record.conrelid
                JOIN pg_namespace namespace_record
                  ON namespace_record.oid = table_record.relnamespace
                WHERE namespace_record.nspname = 'public'
                  AND table_record.relname = :table
                  AND constraint_record.conname IN (
                    'ck_support_assistant_usage_persona',
                    'ck_support_assistant_usage_status'
                  )
                """
            ),
            {"table": TABLE},
        ).scalar_one()

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_enabled, "Assistant usage metadata does not have RLS enabled"
    assert grants == 0, "Assistant usage metadata is exposed through the Data API"
    assert policies == 1, "Owner-only assistant usage policy is missing"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert columns == EXPECTED_COLUMNS, f"Unexpected assistant usage columns: {columns}"
    assert check_constraints == 2, "Assistant persona and status constraints are incomplete"
    print(
        "Support S6 verified: migration head, metadata-only retention, RLS, revoked grants, "
        "owner policy, constraints and rate-limit indexes passed"
    )


if __name__ == "__main__":
    main()
