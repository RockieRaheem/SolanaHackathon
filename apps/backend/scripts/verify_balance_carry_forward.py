from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "e27d4c8a91b0"
TABLES = ("balance_carry_forwards", "balance_carry_forward_lines")
REQUIRED_INDEXES = {
    "uq_balance_carry_source_close",
    "uq_balance_carry_source_period",
    "uq_balance_carry_destination_period",
    "uq_balance_carry_key",
    "uq_balance_carry_line_student",
    "uq_balance_carry_destination_student",
    "uq_balance_carry_source_learner",
    "uq_balance_carry_ledger_entry",
    "ix_balance_carry_school_posted",
    "ix_balance_carry_lines_school_student",
}
REQUIRED_TRIGGERS = {
    "validate_balance_carry_batch",
    "validate_balance_carry_line",
    "validate_balance_carry_totals",
    "protect_balance_carry_batch",
    "protect_balance_carry_line",
    "protect_carried_balance_ledger",
}
REQUIRED_CONSTRAINTS = {
    "ck_balance_carry_learner_count",
    "ck_balance_carry_debt_total",
    "ck_balance_carry_credit_total",
    "ck_balance_carry_net_total",
    "ck_balance_carry_distinct_periods",
    "ck_balance_carry_line_nonzero",
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
        inconsistent_batches = connection.scalar(
            text(
                """
                select count(*)
                from balance_carry_forwards carry
                left join lateral (
                  select count(*) as learner_count,
                         coalesce(sum(case when amount > 0 then amount else 0 end), 0) as debt,
                         coalesce(sum(case when amount < 0 then -amount else 0 end), 0) as credit
                  from balance_carry_forward_lines line
                  where line.carry_forward_id = carry.id
                ) actual on true
                where carry.learner_count <> actual.learner_count
                   or carry.debt_total <> actual.debt
                   or carry.credit_total <> actual.credit
                """
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Balance carry evidence is exposed through the Data API"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert REQUIRED_CONSTRAINTS <= constraints, (
        f"Missing constraints: {REQUIRED_CONSTRAINTS - constraints}"
    )
    assert len(numeric_columns) == 4, "Balance carry money columns are not exact numeric(18,2)"
    assert inconsistent_batches == 0, "A balance carry batch does not match its learner evidence"
    print(
        "Balance carry-forward verified: migration head, exact money, tenant isolation, "
        "next-period validation, immutable evidence and aggregate integrity passed"
    )


if __name__ == "__main__":
    main()
