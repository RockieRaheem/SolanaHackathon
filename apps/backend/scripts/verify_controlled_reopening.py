from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "a72d5e8c19f4"
TABLES = (
    "period_reopenings",
    "period_reopening_corrections",
    "period_reopening_learners",
)
REQUIRED_TRIGGERS = {
    "validate_period_reopening",
    "validate_period_reopening_correction",
    "validate_period_reopening_totals",
    "protect_period_reopenings",
    "protect_period_reopening_corrections",
    "protect_period_reopening_learners",
    "validate_reopening_ledger_entry",
}
REQUIRED_CONSTRAINTS = {
    "uq_period_reopenings_key",
    "uq_period_reopenings_version",
    "uq_reopening_correction_student",
    "uq_reopening_learner",
    "ck_period_reopenings_version",
    "ck_period_reopenings_corrections",
    "ck_reopening_correction_type",
    "ck_reopening_correction_amount",
    "ck_reopening_correction_sign",
    "fk_ledger_entries_reopening_correction_id",
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
        triggers = set(
            connection.scalars(
                text(
                    """
                    select trigger_record.tgname
                    from pg_trigger trigger_record
                    join pg_class relation on relation.oid = trigger_record.tgrelid
                    join pg_namespace namespace on namespace.oid = relation.relnamespace
                    where not trigger_record.tgisinternal
                      and namespace.nspname = 'public'
                      and relation.relname = any(:tables)
                    """
                ),
                {"tables": [*TABLES, "ledger_entries"]},
            )
        )
        constraints = set(
            connection.scalars(
                text("select conname from pg_constraint where conname = any(:constraints)"),
                {"constraints": list(REQUIRED_CONSTRAINTS)},
            )
        )
        correction_column = connection.scalar(
            text(
                """
                select count(*) from information_schema.columns
                where table_schema = 'public' and table_name = 'ledger_entries'
                  and column_name = 'reopening_correction_id'
                """
            )
        )
        inconsistent = connection.scalar(
            text(
                """
                select count(*) from period_reopenings reopening
                left join lateral (
                  select count(*) as correction_count, coalesce(sum(amount), 0) as adjustment
                  from period_reopening_corrections correction
                  where correction.reopening_id = reopening.id
                ) corrections on true
                left join lateral (
                  select count(*) as learner_count
                  from period_reopening_learners learner
                  where learner.reopening_id = reopening.id
                ) learners on true
                where reopening.correction_count <> corrections.correction_count
                   or reopening.learner_count <> learners.learner_count
                   or reopening.net_adjustment <> corrections.adjustment
                """
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Controlled reopening evidence is exposed through the Data API"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert REQUIRED_CONSTRAINTS <= constraints, (
        f"Missing constraints: {REQUIRED_CONSTRAINTS - constraints}"
    )
    assert correction_column == 1, "Ledger entries are not linked to reopening corrections"
    assert inconsistent == 0, "A controlled reopening does not match its sealed evidence"
    print(
        "Controlled reopening verified: migration head, tenant isolation, owner-only writes, "
        "revision chain, correction ledger links, aggregate totals and immutability passed"
    )


if __name__ == "__main__":
    main()
