from sqlalchemy import text

from harambeeone_api.database import get_engine


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.scalar(text("select version_num from alembic_version"))
        assert revision == "f42c8e910ab7", f"Unexpected migration revision: {revision}"
        columns = set(
            connection.scalars(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema='public' and table_name='support_cases'"
                )
            )
        )
        required = {
            "referral_id",
            "guardian_auth_user_id",
            "private_context",
            "review_notes",
            "submitted_at",
            "reviewed_at",
        }
        assert required <= columns, f"Missing support case columns: {required - columns}"
        indexes = dict(
            connection.execute(
                text(
                    "select indexname, indexdef from pg_indexes "
                    "where schemaname='public' and tablename='support_cases'"
                )
            ).all()
        )
        for name in (
            "uq_support_cases_active_general_obligation",
            "uq_support_cases_active_requirement",
        ):
            definition = indexes.get(name, "")
            assert "UNIQUE" in definition and "WHERE" in definition, f"Invalid index: {name}"
        rls_enabled = connection.scalar(
            text(
                "select relrowsecurity from pg_class join pg_namespace on "
                "pg_namespace.oid=pg_class.relnamespace where nspname='public' "
                "and relname='support_cases'"
            )
        )
        assert rls_enabled is True, "support_cases RLS is not enabled"
        policy_count = connection.scalar(
            text(
                "select count(*) from pg_policies where schemaname='public' "
                "and tablename='support_cases'"
            )
        )
        assert policy_count >= 2, "support_cases tenant policies are missing"
        exposed_grants = connection.scalar(
            text(
                "select count(*) from information_schema.role_table_grants "
                "where table_schema='public' and table_name='support_cases' "
                "and grantee in ('anon','authenticated')"
            )
        )
        assert exposed_grants == 0, "support_cases has exposed Data API grants"
    print("Guardian-authored support case schema, uniqueness and RLS verification passed.")


if __name__ == "__main__":
    main()
