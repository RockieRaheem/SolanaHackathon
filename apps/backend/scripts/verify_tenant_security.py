from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_TENANT_TABLES = 26


def main() -> None:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        policy_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND (
                    policyname LIKE '%_tenant_select'
                    OR policyname LIKE '%_tenant_write'
                  )
                """
            )
        ).scalar_one()
        rls_tables = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_class AS table_record
                JOIN pg_namespace AS schema_record
                  ON schema_record.oid = table_record.relnamespace
                WHERE schema_record.nspname = 'public'
                  AND table_record.relrowsecurity
                  AND table_record.relname != 'alembic_version'
                """
            )
        ).scalar_one()
        role_constraint = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'ck_school_memberships_role'
                """
            )
        ).scalar_one()
        public_execute = connection.execute(
            text(
                """
                SELECT has_function_privilege(
                    'public',
                    'private.has_school_role(uuid,text[])',
                    'EXECUTE'
                )
                """
            )
        ).scalar_one()

    assert revision == "5342e3f4519b", f"Unexpected migration head: {revision}"
    assert policy_count == EXPECTED_TENANT_TABLES * 2
    assert rls_tables >= EXPECTED_TENANT_TABLES + 1
    assert role_constraint == 1
    assert public_execute is False
    print(
        "Tenant security verified: migration head, role constraint, RLS policies, "
        "and private helper privileges are correct"
    )


if __name__ == "__main__":
    main()
