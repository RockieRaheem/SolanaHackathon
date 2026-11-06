from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "d54a9c7e210f"
TABLES = ("arrears_follow_ups", "arrears_payment_promises")
REQUIRED_INDEXES = {
    "ix_arrears_followups_account",
    "ix_arrears_followups_next_action",
    "ix_arrears_promises_account",
}
REQUIRED_TRIGGERS = {
    "protect_arrears_followup_evidence",
    "protect_arrears_promise_evidence",
}
REQUIRED_CONSTRAINTS = {
    "uq_arrears_followup_key",
    "ck_arrears_followups_method",
    "ck_arrears_followups_outcome",
    "uq_arrears_promise_followup",
    "ck_arrears_promises_amount",
    "ck_arrears_promises_paid_baseline",
    "ck_arrears_promises_status",
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

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TABLES), f"RLS missing from {set(TABLES) - rls_tables}"
    assert exposed_grants == 0, "Arrears evidence is exposed through the Data API"
    assert REQUIRED_INDEXES <= indexes, f"Missing indexes: {REQUIRED_INDEXES - indexes}"
    assert REQUIRED_TRIGGERS <= triggers, f"Missing triggers: {REQUIRED_TRIGGERS - triggers}"
    assert REQUIRED_CONSTRAINTS <= constraints, (
        f"Missing constraints: {REQUIRED_CONSTRAINTS - constraints}"
    )
    print(
        "Arrears management verified: migration head, RLS, grants, indexes, "
        "duplicate controls and immutable evidence passed"
    )


if __name__ == "__main__":
    main()
