import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    Enrollment,
    GuardianLink,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    Requirement,
    School,
    SchoolMembership,
    Student,
    StudentRequirement,
)


@pytest.fixture
def payment_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school = School(name="Payment Desk School", district="Wakiso")
        other_school = School(name="Other School")
        session.add_all([school, other_school])
        session.flush()
        year = AcademicYear(
            school_id=school.id,
            name="2027 Academic Year",
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status="open",
        )
        session.add(year)
        session.flush()
        period = AcademicPeriod(
            academic_year_id=year.id,
            school_id=school.id,
            name="Term 1",
            sequence=1,
            opening_date=date(2027, 1, 10),
            due_date=date(2027, 2, 10),
            closing_date=date(2027, 4, 20),
            status="open",
        )
        academic_class = AcademicClass(
            school_id=school.id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        learner_person = Person(first_name="Amina", last_name="Kato")
        guardian = Person(
            first_name="Sarah", last_name="Kato", phone="+256700123456"
        )
        session.add_all([period, academic_class, learner_person, guardian])
        session.flush()
        learner = Student(
            school_id=school.id,
            person_id=learner_person.id,
            admission_no="PAY-001",
            gender="female",
        )
        session.add(learner)
        session.flush()
        requirement = Requirement(
            school_id=school.id,
            period_id=period.id,
            name="Candidate uniform",
            code="P7-UNIFORM",
            requirement_type="school_item",
            academic_year=2027,
            term=1,
            amount=Decimal("100000"),
            quantity=Decimal("1"),
            unit="set",
            status="published",
        )
        session.add(requirement)
        session.flush()
        assignment = StudentRequirement(
            requirement_id=requirement.id,
            student_id=learner.id,
            expected_amount=Decimal("100000"),
            expected_quantity=Decimal("1"),
        )
        session.add_all(
            [
                assignment,
                Enrollment(
                    student_id=learner.id,
                    class_id=academic_class.id,
                    period_id=period.id,
                    academic_year=2027,
                    term=1,
                ),
                GuardianLink(
                    student_id=learner.id,
                    person_id=guardian.id,
                    relationship="mother",
                    is_primary=True,
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=learner.id,
                    entry_type="fee_charge",
                    amount=Decimal("300000"),
                    reference="FEES-2027-T1",
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=learner.id,
                    entry_type="requirement_charge",
                    amount=Decimal("100000"),
                    reference=f"REQ:{assignment.id}",
                    requirement_assignment_id=assignment.id,
                ),
                SchoolMembership(
                    school_id=school.id, auth_user_id=user_id, role="owner"
                ),
            ]
        )
        session.commit()
        ids = {
            "school": school.id,
            "other_school": other_school.id,
            "period": period.id,
            "learner": learner.id,
            "assignment": assignment.id,
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


def payment_payload(ids: dict) -> dict:
    return {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "student_id": str(ids["learner"]),
        "external_reference": "SP-2027-0001",
        "payer_name": "Sarah Kato",
        "channel": "schoolpay",
        "amount": 250_000,
        "allocations": [
            {"allocation_type": "fees", "amount": 150_000},
            {
                "allocation_type": "requirement",
                "amount": 75_000,
                "requirement_assignment_id": str(ids["assignment"]),
            },
            {"allocation_type": "unallocated", "amount": 25_000},
        ],
    }


def test_search_channels_split_payment_and_retry_are_consistent(payment_workspace) -> None:
    engine, ids, client = payment_workspace
    channels = client.get(
        "/api/v1/payment-channels", params={"school_id": str(ids["school"])}
    )
    assert channels.status_code == 200, channels.text
    assert {item["code"] for item in channels.json()} >= {
        "cash",
        "bank",
        "mobile_money",
        "schoolpay",
    }

    for term in ("PAY-001", "Sarah", "+256700123456"):
        search = client.get(
            "/api/v1/payment-desk/learners",
            params={
                "school_id": str(ids["school"]),
                "period_id": str(ids["period"]),
                "q": term,
            },
        )
        assert search.status_code == 200, search.text
        assert search.json()[0]["id"] == str(ids["learner"])

    before = client.get(
        f"/api/v1/payment-desk/learners/{ids['learner']}/obligations",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert before.status_code == 200, before.text
    assert Decimal(before.json()["account_balance"]) == Decimal("400000")

    posted = client.post("/api/v1/payments", json=payment_payload(ids))
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["receipt_no"].endswith("000001")
    assert {item["allocation_type"] for item in body["allocations"]} == {
        "fees",
        "requirement",
        "unallocated",
    }

    retried = client.post("/api/v1/payments", json=payment_payload(ids))
    assert retried.status_code == 201, retried.text
    assert retried.json()["id"] == body["id"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(Payment.id))) == 1
        assert session.scalar(select(func.count(PaymentAllocation.id))) == 3
        assert session.scalar(
            select(func.sum(LedgerEntry.amount)).where(
                LedgerEntry.student_id == ids["learner"]
            )
        ) == Decimal("150000")

    after = client.get(
        f"/api/v1/payment-desk/learners/{ids['learner']}/obligations",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    ).json()
    assert Decimal(after["fees"]["outstanding"]) == Decimal("150000")
    assert Decimal(after["requirements"][0]["outstanding"]) == Decimal("25000")
    assert Decimal(after["unallocated_credit"]) == Decimal("25000")

    receipt = client.get(f"/api/v1/payments/{body['id']}/receipt")
    assert receipt.status_code == 200, receipt.text
    assert Decimal(receipt.json()["paid_to_date"]) == Decimal("250000")
    dashboard = client.get(
        "/api/v1/dashboard",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert dashboard.status_code == 200, dashboard.text
    assert Decimal(str(dashboard.json()["metrics"]["collected"])) == Decimal("250000")


def test_correction_is_linked_idempotent_and_restores_balances(payment_workspace) -> None:
    engine, ids, client = payment_workspace
    original = client.post("/api/v1/payments", json=payment_payload(ids)).json()
    correction_payload = {
        "action": "refund",
        "amount": 50_000,
        "reason": "Duplicate amount confirmed by the bursar",
        "idempotency_key": "refund-request-0001",
    }
    corrected = client.post(
        f"/api/v1/payments/{original['id']}/corrections", json=correction_payload
    )
    assert corrected.status_code == 200, corrected.text
    correction = corrected.json()
    assert correction["transaction_type"] == "refund"
    assert Decimal(correction["amount"]) == Decimal("-50000")
    assert correction["original_payment_id"] == original["id"]
    assert correction["receipt_no"].endswith("000002")

    retried = client.post(
        f"/api/v1/payments/{original['id']}/corrections", json=correction_payload
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == correction["id"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(Payment.id))) == 2
        persisted = session.get(Payment, uuid.UUID(original["id"]))
        assert persisted.status == "partially_refunded"
        assert session.scalar(
            select(func.sum(LedgerEntry.amount)).where(
                LedgerEntry.student_id == ids["learner"]
            )
        ) == Decimal("200000")

    report = client.get(
        "/api/v1/reports/collections",
        params={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "start_date": "2020-01-01",
            "end_date": "2030-12-31",
        },
    )
    assert report.status_code == 200, report.text
    assert Decimal(report.json()["collected"]) == Decimal("200000")
    assert report.json()["transaction_count"] == 2

    reissue = client.post(
        f"/api/v1/payments/{original['id']}/reissues",
        json={"reason": "Guardian requested a replacement copy"},
    )
    assert reissue.status_code == 200, reissue.text
    receipt = client.get(f"/api/v1/payments/{original['id']}/receipt").json()
    assert receipt["reissue_count"] == 1
    assert Decimal(receipt["corrected_total"]) == Decimal("50000")


def test_invalid_split_and_cross_school_requests_leave_no_partial_history(
    payment_workspace,
) -> None:
    engine, ids, client = payment_workspace
    invalid = payment_payload(ids)
    invalid["allocations"][0]["amount"] = 150_001
    response = client.post("/api/v1/payments", json=invalid)
    assert response.status_code == 422, response.text
    forbidden = client.get(
        "/api/v1/payment-channels", params={"school_id": str(ids["other_school"])}
    )
    assert forbidden.status_code == 403
    with Session(engine) as session:
        assert session.scalar(select(func.count(Payment.id))) == 0
        assert session.scalar(select(func.count(PaymentAllocation.id))) == 0
