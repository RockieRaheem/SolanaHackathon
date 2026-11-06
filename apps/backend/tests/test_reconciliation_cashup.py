import uuid
from datetime import UTC, date, datetime
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
    CashierBatchPayment,
    CashierCollectionBatch,
    Enrollment,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    School,
    SchoolMembership,
    StatementImport,
    StatementTransaction,
    Student,
)


@pytest.fixture
def reconciliation_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school = School(name="Reconciliation School")
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
            opening_date=date(2027, 1, 5),
            due_date=date(2027, 2, 5),
            closing_date=date(2027, 4, 30),
            status="open",
        )
        academic_class = AcademicClass(
            school_id=school.id,
            name="Primary Seven",
            level="primary",
            sort_order=7,
        )
        person = Person(first_name="Amina", last_name="Kato")
        session.add_all([period, academic_class, person])
        session.flush()
        student = Student(
            school_id=school.id,
            person_id=person.id,
            admission_no="REC-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        membership = SchoolMembership(
            school_id=school.id,
            auth_user_id=user_id,
            member_email="owner@example.com",
            role="owner",
        )
        session.add_all(
            [
                membership,
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=period.id,
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("500000"),
                    reference="TERM-FEES",
                ),
            ]
        )
        session.commit()
        ids = {
            "school": school.id,
            "other_school": other_school.id,
            "period": period.id,
            "student": student.id,
            "membership": membership.id,
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


def import_payload(ids: dict, *, key: str = "schoolpay-import-0001") -> dict:
    return {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "file_name": "schoolpay-october.csv",
        "source_type": "schoolpay",
        "idempotency_key": key,
        "content": (
            "Payment Date,Payment Reference,Paid Amount,Student Code\n"
            "2027-02-01,SP-001,200000,REC-001\n"
            "2027-02-02,SP-002,75000,UNKNOWN\n"
        ),
    }


def test_provider_import_review_confirm_and_undo_are_controlled(
    reconciliation_workspace,
) -> None:
    engine, ids, client = reconciliation_workspace
    imported = client.post("/api/v1/reconciliation/file-imports", json=import_payload(ids))
    assert imported.status_code == 201, imported.text
    assert imported.json()["row_count"] == 2
    assert Decimal(imported.json()["total_amount"]) == Decimal("275000")

    retried = client.post("/api/v1/reconciliation/file-imports", json=import_payload(ids))
    assert retried.status_code == 201, retried.text
    assert retried.json()["id"] == imported.json()["id"]
    duplicate = client.post(
        "/api/v1/reconciliation/file-imports",
        json=import_payload(ids, key="schoolpay-import-0002"),
    )
    assert duplicate.status_code == 409

    transactions = client.get(
        "/api/v1/reconciliation/transactions",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert transactions.status_code == 200, transactions.text
    items = transactions.json()
    suggested = next(item for item in items if item["source_reference"] == "SP-001")
    unmatched = next(item for item in items if item["source_reference"] == "SP-002")
    assert suggested["status"] == "suggested"
    assert suggested["match_reason"] == "Exact admission number in source record"
    assert Decimal(suggested["confidence"]) == Decimal("1.0000")

    held = client.post(
        f"/api/v1/reconciliation/transactions/{unmatched['id']}/decision",
        json={"action": "unidentified", "reason": "No reliable learner reference supplied"},
    )
    assert held.status_code == 200, held.text
    assert held.json()["status"] == "unidentified"

    confirmed = client.post(
        f"/api/v1/reconciliation/transactions/{suggested['id']}/confirm",
        json={"student_id": str(ids["student"]), "period_id": str(ids["period"])},
    )
    assert confirmed.status_code == 201, confirmed.text
    payment_id = confirmed.json()["payment_id"]
    again = client.post(
        f"/api/v1/reconciliation/transactions/{suggested['id']}/confirm",
        json={"student_id": str(ids["student"])},
    )
    assert again.status_code == 201, again.text
    assert again.json()["payment_id"] == payment_id

    with Session(engine) as session:
        assert session.scalar(select(func.count(StatementImport.id))) == 1
        assert session.scalar(select(func.count(StatementTransaction.id))) == 2
        assert session.scalar(select(func.count(Payment.id))) == 1
        assert session.scalar(select(func.count(PaymentAllocation.id))) == 1
        assert session.scalar(
            select(func.sum(LedgerEntry.amount)).where(LedgerEntry.student_id == ids["student"])
        ) == Decimal("300000")

    undone = client.post(
        f"/api/v1/reconciliation/transactions/{suggested['id']}/undo",
        json={
            "reason": "Bank confirmed the transaction was returned",
            "idempotency_key": "undo-schoolpay-0001",
        },
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["receipt_no"].endswith("000002")
    repeated_undo = client.post(
        f"/api/v1/reconciliation/transactions/{suggested['id']}/undo",
        json={
            "reason": "Bank confirmed the transaction was returned",
            "idempotency_key": "undo-schoolpay-0001",
        },
    )
    assert repeated_undo.status_code == 200, repeated_undo.text
    assert repeated_undo.json()["payment_id"] == undone.json()["payment_id"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(Payment.id))) == 2
        original = session.get(Payment, uuid.UUID(payment_id))
        assert original.status == "reversed"
        assert session.scalar(
            select(func.sum(LedgerEntry.amount)).where(LedgerEntry.student_id == ids["student"])
        ) == Decimal("500000")

    summary = client.get(
        "/api/v1/reconciliation/summary",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    )
    assert summary.status_code == 200, summary.text
    assert {item["status"] for item in summary.json()["sources"]} == {
        "reversed",
        "unidentified",
    }


def test_invalid_import_is_atomic_and_tenant_scoped(reconciliation_workspace) -> None:
    engine, ids, client = reconciliation_workspace
    invalid = import_payload(ids)
    invalid["content"] = (
        "Payment Date,Payment Reference,Paid Amount,Student Code\n"
        "2027-02-01,SP-DUP,10000,REC-001\n"
        "bad-date,SP-DUP,10000,REC-001\n"
    )
    response = client.post("/api/v1/reconciliation/file-imports", json=invalid)
    assert response.status_code == 422
    forbidden = import_payload(ids)
    forbidden["school_id"] = str(ids["other_school"])
    denied = client.post("/api/v1/reconciliation/file-imports", json=forbidden)
    assert denied.status_code == 403
    with Session(engine) as session:
        assert session.scalar(select(func.count(StatementImport.id))) == 0
        assert session.scalar(select(func.count(StatementTransaction.id))) == 0


def test_bank_and_mobile_money_adapters_normalize_provider_columns(
    reconciliation_workspace,
) -> None:
    _engine, ids, client = reconciliation_workspace
    files = [
        (
            "bank",
            "Value Date,Transaction Reference,Credit Amount,Narration\n"
            "03/02/2027,BNK-001,45,000,REC-001 fees\n",
            "bank-adapter-0001",
        ),
        (
            "mobile_money",
            "Completion Time,Financial Transaction ID,Received Amount,Customer Name\n"
            "2027-02-04,MOMO-001,35000,Amina Kato\n",
            "mobile-adapter-0001",
        ),
    ]
    # Bank thousands separators must be quoted in standards-compliant CSV.
    files[0] = (
        files[0][0],
        files[0][1].replace("45,000", '"45,000"'),
        files[0][2],
    )
    for source_type, content, key in files:
        response = client.post(
            "/api/v1/reconciliation/file-imports",
            json={
                "school_id": str(ids["school"]),
                "period_id": str(ids["period"]),
                "file_name": f"{source_type}.csv",
                "source_type": source_type,
                "content": content,
                "idempotency_key": key,
            },
        )
        assert response.status_code == 201, response.text
    transactions = client.get(
        "/api/v1/reconciliation/transactions",
        params={"school_id": str(ids["school"]), "period_id": str(ids["period"])},
    ).json()
    assert {item["channel"] for item in transactions} == {"bank", "mobile_money"}
    assert {Decimal(item["amount"]) for item in transactions} == {
        Decimal("45000"),
        Decimal("35000"),
    }


def test_cashier_cash_up_captures_receipts_and_requires_supervisor_signoff(
    reconciliation_workspace,
) -> None:
    engine, ids, client = reconciliation_workspace
    with Session(engine) as session:
        payment = Payment(
            school_id=ids["school"],
            period_id=ids["period"],
            receipt_no="CASH-RECEIPT-1",
            external_reference="CASH-SOURCE-1",
            channel="cash",
            amount=Decimal("80000"),
            created_by="owner@example.com",
            received_at=datetime.now(UTC),
        )
        session.add(payment)
        session.flush()
        session.add(
            PaymentAllocation(
                payment_id=payment.id,
                student_id=ids["student"],
                allocation_type="fees",
                amount=payment.amount,
            )
        )
        session.commit()

    opened = client.post(
        "/api/v1/reconciliation/cash-batches",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "business_date": date.today().isoformat(),
        },
    )
    assert opened.status_code == 201, opened.text
    batch_id = opened.json()["id"]
    submitted_payload = {
        "counted_cash": 80000,
        "deposit_amount": 80000,
        "deposit_reference": "BANK-SLIP-001",
        "note": "Till counted with a witness",
        "idempotency_key": "cashup-submit-0001",
    }
    submitted = client.post(
        f"/api/v1/reconciliation/cash-batches/{batch_id}/submit",
        json=submitted_payload,
    )
    assert submitted.status_code == 200, submitted.text
    assert Decimal(submitted.json()["expected_cash"]) == Decimal("80000")
    assert Decimal(submitted.json()["variance"]) == Decimal("0")
    assert submitted.json()["receipt_count"] == 1
    retry = client.post(
        f"/api/v1/reconciliation/cash-batches/{batch_id}/submit",
        json=submitted_payload,
    )
    assert retry.status_code == 200, retry.text

    approved = client.post(
        f"/api/v1/reconciliation/cash-batches/{batch_id}/decision",
        json={"action": "approve", "note": "Cash and bank deposit agree"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "signed_off"
    assert approved.json()["signed_off_by"] == "owner@example.com"
    with Session(engine) as session:
        assert session.scalar(select(func.count(CashierCollectionBatch.id))) == 1
        assert session.scalar(select(func.count(CashierBatchPayment.id))) == 1


def test_cashier_can_open_own_batch_but_cannot_reconcile_sources(
    reconciliation_workspace,
) -> None:
    engine, ids, client = reconciliation_workspace
    with Session(engine) as session:
        membership = session.get(SchoolMembership, ids["membership"])
        membership.role = "cashier"
        session.commit()
    denied = client.post("/api/v1/reconciliation/file-imports", json=import_payload(ids))
    assert denied.status_code == 403
    opened = client.post(
        "/api/v1/reconciliation/cash-batches",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "business_date": date.today().isoformat(),
        },
    )
    assert opened.status_code == 201, opened.text
