"""Verify controlled-billing database guarantees without retaining test data."""

import uuid
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from harambeeone_api.config import get_settings

EXPECTED_HEAD = "81d7c62772c3"
TENANT_TABLES = (
    "billing_adjustments",
    "billing_publications",
    "fee_structure_learners",
    "requirement_learners",
)


def main() -> None:
    engine = create_engine(get_settings().migration_database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        head = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert head == EXPECTED_HEAD, f"Expected {EXPECTED_HEAD}, found {head}"

        tables = connection.execute(
            text(
                """
                select relname, relrowsecurity from pg_class
                where oid in (
                  'billing_adjustments'::regclass,
                  'billing_publications'::regclass,
                  'fee_structure_learners'::regclass,
                  'requirement_learners'::regclass
                ) order by relname
                """
            )
        ).all()
        assert tables == [(name, True) for name in TENANT_TABLES]

        policies = connection.execute(
            text(
                """
                select count(*) from pg_policies
                where schemaname = 'public'
                  and tablename = any(:tables)
                """
            ),
            {"tables": list(TENANT_TABLES)},
        ).scalar_one()
        assert policies == 8, f"Expected eight tenant policies, found {policies}"

        exposed_grants = connection.execute(
            text(
                """
                select count(*) from information_schema.role_table_grants
                where table_schema = 'public'
                  and table_name = any(:tables)
                  and grantee in ('anon', 'authenticated')
                """
            ),
            {"tables": list(TENANT_TABLES)},
        ).scalar_one()
        assert exposed_grants == 0, f"Found {exposed_grants} unexpected Data API grants"

        trigger_names = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    select tgname from pg_trigger
                    where not tgisinternal and tgname in (
                      'billing_adjustments_reject_closed_period',
                      'billing_publications_reject_closed_period',
                      'ledger_entries_immutable',
                      'ledger_entries_reject_closed_period'
                    )
                    """
                )
            )
        }
        assert len(trigger_names) == 4, f"Missing billing triggers: {trigger_names}"

        null_ledger_identity = connection.execute(
            text(
                "select count(*) from ledger_entries "
                "where school_id is null or period_id is null"
            )
        ).scalar_one()
        assert null_ledger_identity == 0

        publication_key = connection.execute(
            text(
                """
                select count(*) from pg_constraint
                where conname in (
                  'uq_billing_publication_key',
                  'uq_ledger_entries_fee_assignment',
                  'uq_ledger_entries_requirement_assignment',
                  'uq_ledger_entries_billing_adjustment'
                )
                """
            )
        ).scalar_one()
        assert publication_key == 4, "Missing idempotency or source uniqueness constraints"

        connection.rollback()
        transaction = connection.begin()
        try:
            school_id, year_id, period_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            person_id, student_id, entry_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            connection.execute(
                text("insert into schools (id, name) values (:id, 'Billing verification')"),
                {"id": school_id},
            )
            connection.execute(
                text(
                    """
                    insert into academic_years
                      (id, school_id, name, year, start_date, end_date, status)
                    values (:id, :school, 'Verification year', 2098, :start, :finish, 'open')
                    """
                ),
                {
                    "id": year_id,
                    "school": school_id,
                    "start": date(2098, 1, 1),
                    "finish": date(2098, 12, 31),
                },
            )
            connection.execute(
                text(
                    """
                    insert into academic_periods
                      (id, academic_year_id, school_id, name, sequence,
                       opening_date, due_date, closing_date, status)
                    values (:id, :year, :school, 'Term 1', 1, :start, :due, :finish, 'open')
                    """
                ),
                {
                    "id": period_id,
                    "year": year_id,
                    "school": school_id,
                    "start": date(2098, 1, 1),
                    "due": date(2098, 2, 1),
                    "finish": date(2098, 4, 1),
                },
            )
            connection.execute(
                text(
                    "insert into people (id, first_name, last_name) "
                    "values (:id, 'Billing', 'Test')"
                ),
                {"id": person_id},
            )
            connection.execute(
                text(
                    """
                    insert into students (id, school_id, person_id, admission_no, gender)
                    values (:id, :school, :person, 'BILLING-VERIFY', 'other')
                    """
                ),
                {"id": student_id, "school": school_id, "person": person_id},
            )
            connection.execute(
                text(
                    """
                    insert into ledger_entries
                      (id, school_id, period_id, student_id, entry_type,
                       amount, currency, reference)
                    values
                      (:id, :school, :period, :student, 'fee_charge',
                       1000, 'UGX', 'VERIFY:IMMUTABLE')
                    """
                ),
                {
                    "id": entry_id,
                    "school": school_id,
                    "period": period_id,
                    "student": student_id,
                },
            )
            savepoint = connection.begin_nested()
            try:
                connection.execute(
                    text("update ledger_entries set amount = 999 where id = :id"),
                    {"id": entry_id},
                )
            except DBAPIError as error:
                savepoint.rollback()
                assert "immutable" in str(error).lower()
            else:
                raise AssertionError("Database accepted a posted ledger mutation")
        finally:
            transaction.rollback()
    engine.dispose()
    print(
        "Controlled billing verified: migration head, RLS, policies, grants, triggers, "
        "backfill, idempotency constraints, and immutable ledger protection passed"
    )


if __name__ == "__main__":
    main()
