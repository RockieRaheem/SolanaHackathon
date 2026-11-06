from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "c91b7e2a4f60"
TABLES = ("learner_rollovers", "learner_rollover_lines")
REQUIRED_TRIGGERS = {
    "validate_learner_rollover_batch",
    "validate_learner_rollover_line",
    "validate_learner_rollover_totals",
    "protect_learner_rollover_batch",
    "protect_learner_rollover_line",
}
REQUIRED_CONSTRAINTS = {
    "uq_learner_rollovers_source_close",
    "uq_learner_rollovers_source_period",
    "uq_learner_rollovers_destination_period",
    "uq_learner_rollovers_key",
    "uq_rollover_lines_student",
    "uq_rollover_lines_source_learner",
    "uq_rollover_lines_enrollment",
    "ck_learner_rollovers_candidates",
    "ck_learner_rollovers_decision_totals",
    "ck_learner_rollovers_distinct_periods",
    "ck_rollover_lines_decision",
    "ck_rollover_lines_result",
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
                {"tables": list(TABLES)},
            )
        )
        constraints = set(
            connection.scalars(
                text("select conname from pg_constraint where conname = any(:constraints)"),
                {"constraints": list(REQUIRED_CONSTRAINTS)},
            )
        )
        inconsistent_batches = connection.scalar(
            text(
                """
                select count(*) from learner_rollovers rollover
                left join lateral (
                  select count(*) as total,
                         count(*) filter (
                           where decision in ('continue','promote','repeat')
                         ) as placed,
                         count(*) filter (where decision = 'hold') as held,
                         count(*) filter (where decision = 'complete') as completed,
                         count(*) filter (where decision = 'depart') as departed
                  from learner_rollover_lines line where line.rollover_id = rollover.id
                ) actual on true
                where (rollover.candidate_count, rollover.placed_count, rollover.held_count,
                       rollover.completed_count, rollover.departed_count)
                   <> (actual.total, actual.placed, actual.held, actual.completed, actual.departed)
                """
            )
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Learner rollover evidence is exposed through the Data API"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert REQUIRED_CONSTRAINTS <= constraints, (
        f"Missing constraints: {REQUIRED_CONSTRAINTS - constraints}"
    )
    assert inconsistent_batches == 0, "A rollover batch does not match its learner decisions"
    print(
        "Learner rollover verified: migration head, tenant isolation, next-period and "
        "balance prerequisites, decision integrity, aggregate totals and immutability passed"
    )


if __name__ == "__main__":
    main()
