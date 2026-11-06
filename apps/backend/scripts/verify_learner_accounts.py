"""Verify learner-account database support and calculations without retaining data."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from harambeeone_api.accounts import _statement_payload
from harambeeone_api.auth import AuthenticatedUser, SchoolContext
from harambeeone_api.config import get_settings
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    Enrollment,
    LedgerEntry,
    Person,
    School,
    Student,
)

EXPECTED_HEAD = "189d96d367f9"


def main() -> None:
    engine = create_engine(get_settings().migration_database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        head = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert head == EXPECTED_HEAD, f"Expected {EXPECTED_HEAD}, found {head}"
        index_definition = connection.execute(
            text(
                """
                select indexdef from pg_indexes
                where schemaname = 'public'
                  and indexname = 'ix_ledger_entries_student_created'
                """
            )
        ).scalar_one()
        assert "student_id, created_at, id" in index_definition
        immutable_trigger = connection.execute(
            text(
                """
                select count(*) from pg_trigger
                where not tgisinternal
                  and tgname = 'ledger_entries_immutable'
                """
            )
        ).scalar_one()
        assert immutable_trigger == 1

        connection.rollback()
        transaction = connection.begin()
        try:
            with Session(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                school = School(id=uuid.uuid4(), name="Account verification school")
                session.add(school)
                session.flush()
                year = AcademicYear(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    name="Verification year",
                    year=2096,
                    start_date=date(2096, 1, 1),
                    end_date=date(2096, 12, 31),
                    status="open",
                )
                session.add(year)
                session.flush()
                first = AcademicPeriod(
                    id=uuid.uuid4(),
                    academic_year_id=year.id,
                    school_id=school.id,
                    name="Term 1",
                    sequence=1,
                    opening_date=date(2096, 1, 1),
                    due_date=date(2096, 2, 1),
                    closing_date=date(2096, 4, 1),
                    status="draft",
                )
                second = AcademicPeriod(
                    id=uuid.uuid4(),
                    academic_year_id=year.id,
                    school_id=school.id,
                    name="Term 2",
                    sequence=2,
                    opening_date=date(2096, 5, 1),
                    due_date=date(2096, 6, 1),
                    closing_date=date(2096, 8, 1),
                    status="open",
                )
                academic_class = AcademicClass(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    name="Verification class",
                    level="other",
                    sort_order=1,
                )
                person = Person(id=uuid.uuid4(), first_name="Account", last_name="Learner")
                session.add_all([first, second, academic_class, person])
                session.flush()
                student = Student(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    person_id=person.id,
                    admission_no="ACCOUNT-VERIFY",
                    gender="other",
                )
                session.add(student)
                session.flush()
                session.add_all(
                    [
                        Enrollment(
                            id=uuid.uuid4(),
                            student_id=student.id,
                            class_id=academic_class.id,
                            period_id=first.id,
                            academic_year=2096,
                            term=1,
                        ),
                        Enrollment(
                            id=uuid.uuid4(),
                            student_id=student.id,
                            class_id=academic_class.id,
                            period_id=second.id,
                            academic_year=2096,
                            term=2,
                        ),
                        LedgerEntry(
                            id=uuid.uuid4(),
                            school_id=school.id,
                            period_id=first.id,
                            student_id=student.id,
                            entry_type="fee_charge",
                            amount=Decimal("50"),
                            reference="VERIFY-OPENING",
                            created_at=datetime(2096, 1, 5, tzinfo=UTC),
                        ),
                        LedgerEntry(
                            id=uuid.uuid4(),
                            school_id=school.id,
                            period_id=second.id,
                            student_id=student.id,
                            entry_type="fee_charge",
                            amount=Decimal("100"),
                            reference="VERIFY-CHARGE",
                            created_at=datetime(2096, 5, 5, tzinfo=UTC),
                        ),
                        LedgerEntry(
                            id=uuid.uuid4(),
                            school_id=school.id,
                            period_id=second.id,
                            student_id=student.id,
                            entry_type="payment",
                            amount=Decimal("-30"),
                            reference="VERIFY-PAYMENT",
                            created_at=datetime(2096, 5, 6, tzinfo=UTC),
                        ),
                    ]
                )
                session.flush()
                context = SchoolContext(
                    user=AuthenticatedUser(id=uuid.uuid4(), email="verification@harambeeone.local"),
                    school_id=school.id,
                    role="owner",
                )
                statement = _statement_payload(
                    session,
                    student_id=student.id,
                    period_id=second.id,
                    context=context,
                )
                assert statement["summary"]["opening_balance"] == "50.00"
                assert statement["summary"]["period_activity"] == "70.00"
                assert statement["summary"]["closing_balance"] == "120.00"
                assert [line["balance"] for line in statement["lines"]] == [
                    "50.00",
                    "150.00",
                    "120.00",
                ]
        finally:
            transaction.rollback()
    engine.dispose()
    print(
        "Learner accounts verified: migration head, chronological index, immutable ledger, "
        "opening balance, period activity, and running balance passed"
    )


if __name__ == "__main__":
    main()
