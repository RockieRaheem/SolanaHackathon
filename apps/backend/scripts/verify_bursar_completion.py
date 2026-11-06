"""Verify the complete bursar control boundary on the live Supabase schema."""

from sqlalchemy import text

from harambeeone_api.database import get_engine

EXPECTED_HEAD = "a72d5e8c19f4"
TENANT_TABLES = (
    "academic_years",
    "academic_periods",
    "school_memberships",
    "academic_classes",
    "streams",
    "students",
    "enrollments",
    "guardian_links",
    "fee_structures",
    "fee_categories",
    "student_fee_assignments",
    "requirements",
    "student_requirements",
    "payments",
    "payment_allocations",
    "billing_publications",
    "billing_adjustments",
    "ledger_entries",
    "arrears_follow_ups",
    "arrears_payment_promises",
    "statement_imports",
    "statement_transactions",
    "cashier_collection_batches",
    "cashier_batch_payments",
    "period_closes",
    "period_close_learners",
    "balance_carry_forwards",
    "balance_carry_forward_lines",
    "learner_rollovers",
    "learner_rollover_lines",
    "period_reopenings",
    "period_reopening_corrections",
    "period_reopening_learners",
    "audit_events",
)
RETRY_CONSTRAINTS = {
    "uq_billing_publication_key",
    "uq_payment_correction_key",
    "uq_statement_import_key",
    "uq_period_closes_key",
    "uq_balance_carry_key",
    "uq_learner_rollovers_key",
    "uq_period_reopenings_key",
}
IMMUTABILITY_TRIGGERS = {
    "ledger_entries_immutable",
    "statement_import_source_immutable",
    "statement_transaction_source_immutable",
    "protect_period_close_snapshot",
    "protect_period_close_learner_snapshot",
    "protect_balance_carry_batch",
    "protect_balance_carry_line",
    "protect_learner_rollover_batch",
    "protect_learner_rollover_line",
    "protect_period_reopenings",
    "protect_period_reopening_corrections",
    "protect_period_reopening_learners",
}


def _scalar(connection, statement: str, **parameters) -> int:
    return connection.scalar(text(statement), parameters)


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
                {"tables": list(TENANT_TABLES)},
            )
        )
        exposed_grants = _scalar(
            connection,
            """
            select count(*) from information_schema.role_table_grants
            where table_schema = 'public' and table_name = any(:tables)
              and grantee in ('anon', 'authenticated')
            """,
            tables=list(TENANT_TABLES),
        )
        constraints = set(
            connection.scalars(
                text("select conname from pg_constraint where conname = any(:names)"),
                {"names": list(RETRY_CONSTRAINTS)},
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
                    where not trigger_record.tgisinternal and namespace.nspname = 'public'
                      and trigger_record.tgname = any(:names)
                    """
                ),
                {"names": list(IMMUTABILITY_TRIGGERS)},
            )
        )
        invalid_learner_equations = _scalar(
            connection,
            """
            select count(*) from period_close_learners
            where opening_balance + net_assessed - net_collected <> closing_balance
               or greatest(closing_balance, 0) <> outstanding
               or greatest(-closing_balance, 0) <> credit_balance
            """,
        )
        invalid_school_equations = _scalar(
            connection,
            """
            select count(*) from period_closes close
            left join lateral (
              select count(*) as learners,
                     coalesce(sum(opening_balance), 0) as opening_balance,
                     coalesce(sum(net_assessed), 0) as net_assessed,
                     coalesce(sum(net_collected), 0) as net_collected,
                     coalesce(sum(closing_balance), 0) as closing_balance,
                     coalesce(sum(outstanding), 0) as outstanding,
                     coalesce(sum(credit_balance), 0) as credit_balance
              from period_close_learners learner where learner.period_close_id = close.id
            ) totals on true
            where close.opening_balance + close.net_assessed - close.net_collected
                    <> close.closing_balance
               or close.learner_count <> totals.learners
               or close.opening_balance <> totals.opening_balance
               or close.net_assessed <> totals.net_assessed
               or close.net_collected <> totals.net_collected
               or close.closing_balance <> totals.closing_balance
               or close.outstanding <> totals.outstanding
               or close.credit_balance <> totals.credit_balance
            """,
        )
        tenant_mismatches = _scalar(
            connection,
            """
            select
              (select count(*) from ledger_entries ledger
               join students learner on learner.id = ledger.student_id
               join academic_periods period on period.id = ledger.period_id
               where ledger.school_id <> learner.school_id
                  or ledger.school_id <> period.school_id)
              +
              (select count(*) from enrollments enrollment
               join students learner on learner.id = enrollment.student_id
               join academic_classes class on class.id = enrollment.class_id
               join academic_periods period on period.id = enrollment.period_id
               where learner.school_id <> class.school_id
                  or learner.school_id <> period.school_id)
              +
              (select count(*) from period_close_learners learner
               join period_closes close on close.id = learner.period_close_id
               where learner.school_id <> close.school_id
                  or learner.period_id <> close.period_id)
            """,
        )
        missing_audit_actors = _scalar(
            connection,
            """
            select count(*) from audit_events
            where actor is null or btrim(actor) = ''
            """,
        )
        invalid_carries = _scalar(
            connection,
            """
            select count(*) from balance_carry_forwards carry
            left join lateral (
              select count(*) as learners,
                     coalesce(sum(case when amount > 0 then amount else 0 end), 0) as debt,
                     coalesce(sum(case when amount < 0 then -amount else 0 end), 0) as credit,
                     coalesce(sum(amount), 0) as net
              from balance_carry_forward_lines line where line.carry_forward_id = carry.id
            ) totals on true
            where carry.learner_count <> totals.learners
               or carry.debt_total <> totals.debt
               or carry.credit_total <> totals.credit
               or carry.net_balance <> totals.net
            """,
        )

    assert revision == EXPECTED_HEAD, f"Unexpected migration head: {revision}"
    assert rls_tables == set(TENANT_TABLES), f"RLS missing from {set(TENANT_TABLES)-rls_tables}"
    assert exposed_grants == 0, "Operational bursar tables are exposed through the Data API"
    assert constraints == RETRY_CONSTRAINTS, (
        f"Missing retry constraints: {RETRY_CONSTRAINTS-constraints}"
    )
    assert triggers == IMMUTABILITY_TRIGGERS, (
        f"Missing immutable evidence triggers: {IMMUTABILITY_TRIGGERS-triggers}"
    )
    assert invalid_learner_equations == 0, "A sealed learner balance fails the financial equation"
    assert invalid_school_equations == 0, "A sealed school total does not equal its learners"
    assert tenant_mismatches == 0, "Cross-school operational evidence exists"
    assert missing_audit_actors == 0, "Consequential audit evidence is missing its actor"
    assert invalid_carries == 0, "A carry-forward batch does not equal its immutable lines"
    print(
        "Bursar completion verified: migration head, tenant isolation, retry safety, "
        "immutable evidence, financial equations, audit actors and carry totals passed"
    )


if __name__ == "__main__":
    main()
