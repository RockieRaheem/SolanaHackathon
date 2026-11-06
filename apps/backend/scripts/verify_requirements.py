"""Verify the class requirement lifecycle against the configured database without retaining data."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from harambeeone_api.auth import AuthenticatedUser, SchoolContext
from harambeeone_api.billing import _billing_preview, publish_billing
from harambeeone_api.database import get_engine
from harambeeone_api.finance import record_payment
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    Enrollment,
    Person,
    School,
    Student,
)
from harambeeone_api.requirements import (
    create_requirement,
    fulfil_requirement,
    list_requirement_assignments,
)
from harambeeone_api.schemas import (
    BillingPublishCreate,
    PaymentCreate,
    RequirementCreate,
    RequirementFulfilmentCreate,
)


def main() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, expire_on_commit=False) as session:
                school = School(id=uuid.uuid4(), name="Requirement verification school")
                session.add(school)
                session.flush()
                year = AcademicYear(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    name="Verification year",
                    year=2097,
                    start_date=date(2097, 1, 1),
                    end_date=date(2097, 12, 31),
                    status="open",
                )
                session.add(year)
                session.flush()
                period = AcademicPeriod(
                    id=uuid.uuid4(),
                    academic_year_id=year.id,
                    school_id=school.id,
                    name="Term 1",
                    sequence=1,
                    opening_date=date(2097, 1, 1),
                    due_date=date(2097, 2, 1),
                    closing_date=date(2097, 4, 1),
                    status="open",
                )
                academic_class = AcademicClass(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    name="S.4 Verification",
                    level="lower_secondary",
                    canonical_code="VERIFY_S4",
                    sort_order=1,
                )
                person = Person(id=uuid.uuid4(), first_name="Test", last_name="Candidate")
                student = Student(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    person_id=person.id,
                    admission_no=f"VERIFY-{uuid.uuid4().hex[:8]}",
                    gender="female",
                )
                enrollment = Enrollment(
                    id=uuid.uuid4(),
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=period.id,
                    academic_year=2097,
                    term=1,
                )
                session.add_all([period, academic_class, person])
                session.flush()
                session.add(student)
                session.flush()
                session.add(enrollment)
                session.commit()
                context = SchoolContext(
                    user=AuthenticatedUser(id=uuid.uuid4(), email="verification@harambeeone.local"),
                    school_id=school.id,
                    role="owner",
                )

                created = create_requirement(
                    RequirementCreate(
                        school_id=school.id,
                        period_id=period.id,
                        name="Candidate T-shirt",
                        code="VERIFY-S4-SHIRT",
                        requirement_type="school_item",
                        academic_year=2097,
                        term=1,
                        amount=Decimal("30000"),
                        quantity=Decimal("1"),
                        unit="shirt",
                        class_ids=[academic_class.id],
                    ),
                    session,
                    context,
                )
                assert created["assigned_count"] == 0
                preview = _billing_preview(session, school.id, period.id)
                publish_billing(
                    BillingPublishCreate(
                        school_id=school.id,
                        period_id=period.id,
                        preview_token=preview["preview_token"],
                        idempotency_key="requirement-verification",
                    ),
                    session,
                    context,
                )
                assignments = list_requirement_assignments(
                    school_id=school.id,
                    period_id=period.id,
                    requirement_id=created["id"],
                    student_id=None,
                    assignment_status=None,
                    session=session,
                    context=context,
                )
                assert assignments[0]["status"] == "unpaid"

                record_payment(
                    PaymentCreate(
                        school_id=school.id,
                        period_id=period.id,
                        student_id=student.id,
                        external_reference=f"VERIFY-{uuid.uuid4().hex}",
                        payer_name="Verification Guardian",
                        channel="cash",
                        amount=Decimal("30000"),
                        requirement_assignment_id=assignments[0]["id"],
                    ),
                    session,
                    context,
                )
                paid = list_requirement_assignments(
                    school_id=school.id,
                    period_id=period.id,
                    requirement_id=created["id"],
                    student_id=None,
                    assignment_status=None,
                    session=session,
                    context=context,
                )
                assert paid[0]["status"] == "paid"

                fulfilled = fulfil_requirement(
                    paid[0]["id"],
                    RequirementFulfilmentCreate(quantity=Decimal("1")),
                    session,
                    context,
                )
                assert fulfilled["status"] == "issued"
                assert (
                    connection.execute(
                        text(
                            "select relrowsecurity from pg_class "
                            "where oid = 'requirements'::regclass"
                        )
                    ).scalar_one()
                    is True
                )
                print("Requirement lifecycle verified: assigned -> paid -> issued; RLS enabled.")
        finally:
            if transaction.is_active:
                transaction.rollback()


if __name__ == "__main__":
    main()
