from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "f13c9b2a4d60"
TABLES = ("period_closes", "period_close_learners")
REQUIRED_INDEXES = {
    "ix_period_closes_school_closed",
    "ix_period_close_learners_school_student",
    "uq_period_closes_period",
    "uq_period_closes_key",
    "uq_period_close_learner",
}
REQUIRED_TRIGGERS = {
    "protect_period_close_snapshot",
    "protect_period_close_learner_snapshot",
}
REQUIRED_CONSTRAINTS = {
    "uq_period_closes_period",
    "uq_period_closes_key",
    "uq_period_close_learner",
    "ck_period_closes_version",
    "ck_period_closes_learner_count",
    "ck_period_closes_warning_count",
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
                {"tables": list(TABLES)},
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
            {"tables": list(TABLES)},
        )
        indexes = set(
            connection.scalars(
                text(
                    """
                    select indexname from pg_indexes
                    where schemaname = 'public' and tablename = any(:tables)
                    """
                ),
                {"tables": list(TABLES)},
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
                {"tables": list(TABLES)},
            )
        )
        constraints = set(
            connection.scalars(
                text(
                    """
                    select conname from pg_constraint
                    where conname = any(:constraints)
                    """
                ),
                {"constraints": list(REQUIRED_CONSTRAINTS)},
            )
        )
        numeric_columns = set(
            connection.scalars(
                text(
                    """
                    select table_name || '.' || column_name
                    from information_schema.columns
                    where table_schema = 'public'
                      and table_name = any(:tables)
                      and data_type = 'numeric'
                      and numeric_precision = 18
                      and numeric_scale = 2
                    """
                ),
                {"tables": list(TABLES)},
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Closing snapshots are exposed through the Data API"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert REQUIRED_CONSTRAINTS <= constraints, (
        f"Missing constraints: {REQUIRED_CONSTRAINTS - constraints}"
    )
    assert len(numeric_columns) == 26, "Closing money columns are not exact numeric(18,2)"
    print(
        "Period close verified: migration head, exact money, RLS, grants, uniqueness, "
        "indexes and immutable snapshots passed"
    )


if __name__ == "__main__":
    main()
