import uuid
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from harambeeone_api.config import get_settings

EXPECTED_HEAD = "20e3e44669b3"


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.migration_database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        head = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert head == EXPECTED_HEAD, f"Expected {EXPECTED_HEAD}, found {head}"

        rows = connection.execute(
            text(
                """
                select relname, relrowsecurity
                from pg_class
                where oid in ('academic_years'::regclass, 'academic_periods'::regclass)
                order by relname
                """
            )
        ).all()
        assert rows == [("academic_periods", True), ("academic_years", True)]

        policies = connection.execute(
            text(
                """
                select count(*) from pg_policies
                where schemaname = 'public'
                  and tablename in ('academic_years', 'academic_periods')
                """
            )
        ).scalar_one()
        assert policies == 4, f"Expected four tenant policies, found {policies}"

        triggers = connection.execute(
            text(
                """
                select count(*) from pg_trigger
                where not tgisinternal
                  and tgname in (
                    'enrollments_reject_closed_period',
                    'fee_structures_reject_closed_period',
                    'requirements_reject_closed_period',
                    'payments_reject_closed_period'
                  )
                """
            )
        ).scalar_one()
        assert triggers == 4, f"Expected four closed-period triggers, found {triggers}"

        null_counts = connection.execute(
            text(
                """
                select
                  (select count(*) from enrollments where period_id is null) +
                  (select count(*) from fee_structures where period_id is null) +
                  (select count(*) from requirements where period_id is null) +
                  (select count(*) from payments where period_id is null)
                """
            )
        ).scalar_one()
        assert null_counts == 0, f"Found {null_counts} records without period identity"

        duplicate_operational = connection.execute(
            text(
                """
                select count(*) from (
                  select school_id from academic_periods
                  where status in ('open', 'closing')
                  group by school_id having count(*) > 1
                ) conflicts
                """
            )
        ).scalar_one()
        assert duplicate_operational == 0

        public_execute = connection.execute(
            text(
                """
                select has_function_privilege(
                  'public', 'private.reject_closed_period_mutation()', 'execute'
                )
                """
            )
        ).scalar_one()
        assert public_execute is False

        connection.rollback()
        transaction = connection.begin()
        try:
            school_id, year_id, period_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            person_id, student_id, class_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            connection.execute(
                text("insert into schools (id, name) values (:id, 'Period verification')"),
                {"id": school_id},
            )
            connection.execute(
                text(
                    """
                    insert into academic_years
                      (id, school_id, name, year, start_date, end_date, status)
                    values
                      (:id, :school, 'Verification year', 2099, :start, :finish, 'closed')
                    """
                ),
                {
                    "id": year_id,
                    "school": school_id,
                    "start": date(2099, 1, 1),
                    "finish": date(2099, 12, 31),
                },
            )
            connection.execute(
                text(
                    """
                    insert into academic_periods
                      (id, academic_year_id, school_id, name, sequence,
                       opening_date, due_date, closing_date, status)
                    values
                      (:id, :year, :school, 'Closed term', 1,
                       :start, :due, :finish, 'closed')
                    """
                ),
                {
                    "id": period_id,
                    "year": year_id,
                    "school": school_id,
                    "start": date(2099, 1, 1),
                    "due": date(2099, 2, 1),
                    "finish": date(2099, 4, 1),
                },
            )
            connection.execute(
                text(
                    "insert into people (id, first_name, last_name) "
                    "values (:id, 'Closed', 'Test')"
                ),
                {"id": person_id},
            )
            connection.execute(
                text(
                    """
                    insert into students (id, school_id, person_id, admission_no, gender)
                    values (:id, :school, :person, 'CLOSED-VERIFY', 'other')
                    """
                ),
                {"id": student_id, "school": school_id, "person": person_id},
            )
            connection.execute(
                text(
                    """
                    insert into academic_classes (id, school_id, name, level, sort_order)
                    values (:id, :school, 'Closed class', 'other', 99)
                    """
                ),
                {"id": class_id, "school": school_id},
            )
            savepoint = connection.begin_nested()
            try:
                connection.execute(
                    text(
                        """
                        insert into enrollments
                          (id, student_id, class_id, period_id, academic_year, term)
                        values (:id, :student, :class, :period, 2099, 1)
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "student": student_id,
                        "class": class_id,
                        "period": period_id,
                    },
                )
            except DBAPIError as error:
                savepoint.rollback()
                assert "closed and cannot be changed" in str(error)
            else:
                raise AssertionError("Database accepted enrollment in a closed period")
        finally:
            transaction.rollback()
    engine.dispose()
    print(
        "Academic period security verified: head, RLS, policies, triggers, "
        "backfill, uniqueness, privileges, and closed-period rejection passed"
    )


if __name__ == "__main__":
    main()
