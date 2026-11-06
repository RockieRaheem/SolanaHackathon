import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    ArrearsFollowUp,
    AuditEvent,
    Enrollment,
    FeeCategory,
    FeeStructure,
    FeeStructureItem,
    GuardianLink,
    InstallmentRule,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    School,
    SchoolMembership,
    Stream,
    Student,
    StudentFeeAssignment,
)


@pytest.fixture
def arrears_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school, other = School(name="Collections School"), School(name="Other School")
        session.add_all([school, other])
        session.flush()
        year = AcademicYear(
            school_id=school.id,
            name="2026 Academic Year",
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="open",
        )
        session.add(year)
        session.flush()
        period = AcademicPeriod(
            academic_year_id=year.id,
            school_id=school.id,
            name="Term 3",
            sequence=3,
            opening_date=date(2026, 7, 1),
            due_date=date(2026, 10, 30),
            closing_date=date(2026, 12, 15),
            status="open",
        )
        academic_class = AcademicClass(
            school_id=school.id, name="Primary Seven", level="primary", sort_order=7
        )
        session.add_all([period, academic_class])
        session.flush()
        stream = Stream(class_id=academic_class.id, name="East")
        learner = Person(first_name="Amina", last_name="Nabirye")
        guardian = Person(first_name="Sarah", last_name="Nabirye", phone="+256700000001")
        session.add_all([stream, learner, guardian])
        session.flush()
        student = Student(
            school_id=school.id,
            person_id=learner.id,
            admission_no="ARR-001",
            gender="female",
            boarding_status="boarding",
        )
        tuition = FeeCategory(
            school_id=school.id,
            name="Tuition",
            code="TUIT",
            category_type="tuition",
        )
        session.add_all([student, tuition])
        session.flush()
        plan = FeeStructure(
            school_id=school.id,
            class_id=academic_class.id,
            stream_id=stream.id,
            period_id=period.id,
            name="Candidate fees",
            academic_year=2026,
            term=3,
            total_amount=Decimal("400"),
            status="published",
        )
        session.add(plan)
        session.flush()
        assignment_id = uuid.uuid4()
        payment = Payment(
            school_id=school.id,
            period_id=period.id,
            receipt_no="ARR-R-001",
            external_reference="ARR-P-001",
            channel="cash",
            amount=Decimal("50"),
        )
        session.add(payment)
        session.flush()
        session.add_all(
            [
                SchoolMembership(
                    school_id=school.id,
                    auth_user_id=user_id,
                    member_email="owner@example.com",
                    role="owner",
                ),
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    stream_id=stream.id,
                    period_id=period.id,
                    academic_year=2026,
                    term=3,
                ),
                GuardianLink(
                    student_id=student.id,
                    person_id=guardian.id,
                    relationship="mother",
                    is_primary=True,
                ),
                FeeStructureItem(
                    fee_structure_id=plan.id, category_id=tuition.id, amount=Decimal("400")
                ),
                *[
                    InstallmentRule(
                        fee_structure_id=plan.id,
                        name=f"Installment {index}",
                        amount=Decimal("100"),
                        due_date=due_date,
                        sort_order=index,
                    )
                    for index, due_date in enumerate(
                        (
                            date(2026, 7, 15),
                            date(2026, 8, 15),
                            date(2026, 9, 15),
                            date(2026, 10, 30),
                        ),
                        start=1,
                    )
                ],
                StudentFeeAssignment(
                    id=assignment_id,
                    student_id=student.id,
                    fee_structure_id=plan.id,
                    amount=Decimal("400"),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("400"),
                    reference="ARR-FEE",
                    fee_assignment_id=assignment_id,
                ),
                PaymentAllocation(
                    payment_id=payment.id, student_id=student.id, amount=Decimal("50")
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=student.id,
                    entry_type="payment",
                    amount=Decimal("-50"),
                    reference="ARR-P-001",
                    payment_id=payment.id,
                ),
            ]
        )
        session.commit()
        ids = {
            "school": school.id,
            "other": other.id,
            "period": period.id,
            "student": student.id,
            "class": academic_class.id,
            "stream": stream.id,
            "category": tuition.id,
            "user": user_id,
        }

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email="owner@example.com"
    )
    try:
        yield engine, ids, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_aging_reasons_and_operational_filters(arrears_workspace) -> None:
    _engine, ids, client = arrears_workspace
    params = {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "as_of": "2026-10-23",
        "class_id": str(ids["class"]),
        "stream_id": str(ids["stream"]),
        "boarding_status": "boarding",
        "fee_category_id": str(ids["category"]),
        "severity": "critical",
    }
    response = client.get("/api/v1/arrears", params=params)
    assert response.status_code == 200, response.text
    register = response.json()
    assert Decimal(register["total_overdue"]) == Decimal("250")
    assert {key: Decimal(value) for key, value in register["aging"].items()} == {
        "current": Decimal("100"),
        "1_30": Decimal("0"),
        "31_60": Decimal("100"),
        "61_90": Decimal("100"),
        "90_plus": Decimal("50"),
    }
    account = register["items"][0]
    assert Decimal(account["balance"]) == Decimal("350")
    assert account["reasons"][0]["name"] == "Tuition"
    assert account["class_id"] == str(ids["class"])
    assert account["stream_id"] == str(ids["stream"])
    params["boarding_status"] = "day"
    assert client.get("/api/v1/arrears", params=params).json()["items"] == []


def test_followup_promise_retry_history_export_and_security(arrears_workspace) -> None:
    engine, ids, client = arrears_workspace
    payload = {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "student_id": str(ids["student"]),
        "contact_method": "call",
        "contacted_person": "Sarah Nabirye",
        "outcome": "commitment",
        "note": "Guardian committed to pay after salary day.",
        "next_action": "Confirm payment",
        "next_action_date": "2026-11-02",
        "promised_amount": "100",
        "promised_due_date": "2026-11-01",
        "idempotency_key": "arrears-followup-0001",
    }
    created = client.post("/api/v1/arrears/follow-ups", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["promise"]["status"] == "active"
    retried = client.post("/api/v1/arrears/follow-ups", json=payload)
    assert retried.status_code == 201
    assert retried.json()["id"] == created.json()["id"]
    history = client.get(
        f"/api/v1/arrears/{ids['student']}/follow-ups",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1
    with Session(engine) as session:
        payment = Payment(
            school_id=ids["school"],
            period_id=ids["period"],
            receipt_no="ARR-R-002",
            external_reference="ARR-P-002",
            channel="cash",
            amount=Decimal("100"),
        )
        session.add(payment)
        session.flush()
        session.add_all(
            [
                PaymentAllocation(
                    payment_id=payment.id,
                    student_id=ids["student"],
                    amount=Decimal("100"),
                ),
                LedgerEntry(
                    school_id=ids["school"],
                    period_id=ids["period"],
                    student_id=ids["student"],
                    entry_type="payment",
                    amount=Decimal("-100"),
                    reference="ARR-P-002",
                    payment_id=payment.id,
                ),
            ]
        )
        session.commit()
    updated_history = client.get(
        f"/api/v1/arrears/{ids['student']}/follow-ups",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    ).json()
    assert updated_history["items"][0]["promise"]["status"] == "kept"
    assert Decimal(updated_history["items"][0]["promise"]["received_since"]) == Decimal("100")
    worklist = client.get(
        "/api/v1/arrears-worklist.csv",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert worklist.status_code == 200
    assert "ARR-001" in worklist.text and "Confirm payment" in worklist.text
    with Session(engine) as session:
        assert session.scalar(select(ArrearsFollowUp)) is not None
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == "created")) is not None
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == ids["user"])
        )
        membership.role = "cashier"
        session.commit()
    denied = client.post(
        "/api/v1/arrears/follow-ups", json=payload | {"idempotency_key": "cashier-denied-0001"}
    )
    assert denied.status_code == 403
    cross_school = client.get(
        "/api/v1/arrears",
        params={"school_id": str(ids["other"]), "period_id": str(ids["period"])},
    )
    assert cross_school.status_code == 403


def test_followup_validation_is_atomic(arrears_workspace) -> None:
    engine, ids, client = arrears_workspace
    response = client.post(
        "/api/v1/arrears/follow-ups",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "student_id": str(ids["student"]),
            "contact_method": "call",
            "contacted_person": "Sarah Nabirye",
            "outcome": "contacted",
            "note": "Contact made.",
            "next_action": "Call again",
            "next_action_date": None,
            "idempotency_key": "invalid-followup-0001",
        },
    )
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(ArrearsFollowUp)) is None
