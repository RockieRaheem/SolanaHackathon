import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api import periods as periods_module
from harambeeone_api import reopening as reopening_module
from harambeeone_api import rollover as rollover_module
from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.financial_reporting import load_learner_financial_totals
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    AuditEvent,
    BalanceCarryForward,
    BalanceCarryForwardLine,
    CashierBatchPayment,
    CashierCollectionBatch,
    Enrollment,
    FeeStructure,
    GuardianLink,
    InstallmentRule,
    LearnerRollover,
    LearnerRolloverLine,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    PeriodClose,
    PeriodCloseLearner,
    PeriodReopening,
    PeriodReopeningCorrection,
    PeriodReopeningLearner,
    Person,
    Requirement,
    School,
    SchoolMembership,
    SchoolProgramme,
    StatementImport,
    StatementTransaction,
    StellarAnchor,
    Student,
    StudentFeeAssignment,
)


@pytest.fixture
def period_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school = School(name="Calendar School")
        other = School(name="Other School")
        session.add_all([school, other])
        session.flush()
        session.add(SchoolMembership(school_id=school.id, auth_user_id=user_id, role="owner"))
        session.commit()
        school_id, other_id = school.id, other.id

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    def user_override():
        return AuthenticatedUser(id=user_id, email="owner@example.com")

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = user_override
    try:
        yield engine, user_id, school_id, other_id, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_year(client: TestClient, school_id: uuid.UUID, year: int = 2027) -> list[dict]:
    response = client.post(
        "/api/v1/academic-years",
        json={
            "school_id": str(school_id),
            "name": f"{year} Academic Year",
            "year": year,
            "start_date": f"{year}-01-10",
            "end_date": f"{year}-12-05",
            "periods": [
                {
                    "name": "Term 1",
                    "sequence": 1,
                    "opening_date": f"{year}-01-10",
                    "due_date": f"{year}-02-10",
                    "closing_date": f"{year}-04-20",
                },
                {
                    "name": "Term 2",
                    "sequence": 2,
                    "opening_date": f"{year}-05-15",
                    "due_date": f"{year}-06-15",
                    "closing_date": f"{year}-08-20",
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["periods"]


def transition(client: TestClient, period_id: str, target: str, reason: str | None = None):
    return client.post(
        f"/api/v1/academic-periods/{period_id}/transition",
        json={"status": target, "reason": reason},
    )


def create_single_period_year(
    client: TestClient, school_id: uuid.UUID, year: int, sequence: int = 1
) -> dict:
    response = client.post(
        "/api/v1/academic-years",
        json={
            "school_id": str(school_id),
            "name": f"{year} Academic Year",
            "year": year,
            "start_date": f"{year}-01-10",
            "end_date": f"{year}-12-05",
            "periods": [
                {
                    "name": f"Term {sequence}",
                    "sequence": sequence,
                    "opening_date": f"{year}-01-10",
                    "due_date": f"{year}-02-10",
                    "closing_date": f"{year}-04-20",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["periods"][0]


def test_dashboard_bootstrap_uses_lightweight_periods(period_workspace) -> None:
    _engine, _user_id, school_id, _other_id, client = period_workspace
    periods = create_year(client, school_id)
    assert transition(client, periods[0]["id"], "open").status_code == 200

    lightweight = client.get("/api/v1/academic-periods")
    assert lightweight.status_code == 200
    assert all(period["activity_count"] is None for period in lightweight.json())

    detailed = client.get("/api/v1/academic-periods?include_activity=true")
    assert detailed.status_code == 200
    assert all(period["activity_count"] == 0 for period in detailed.json())

    response = client.get("/api/v1/dashboard/bootstrap")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["school"]["id"] == str(school_id)
    assert payload["overview"]["period"]["id"] == periods[0]["id"]
    assert len(payload["periods"]) == 2


def test_calendar_is_tenant_scoped_and_rejects_overlapping_dates(period_workspace) -> None:
    _engine, _user_id, school_id, other_id, client = period_workspace
    forbidden = client.post(
        "/api/v1/academic-years",
        json={
            "school_id": str(other_id),
            "name": "2027",
            "year": 2027,
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
            "periods": [
                {
                    "name": "Term 1",
                    "sequence": 1,
                    "opening_date": "2027-01-01",
                    "due_date": "2027-02-01",
                    "closing_date": "2027-04-01",
                }
            ],
        },
    )
    assert forbidden.status_code == 403

    invalid = client.post(
        "/api/v1/academic-years",
        json={
            "school_id": str(school_id),
            "name": "2027",
            "year": 2027,
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
            "periods": [
                {
                    "name": "First",
                    "sequence": 1,
                    "opening_date": "2027-01-01",
                    "due_date": "2027-02-01",
                    "closing_date": "2027-05-01",
                },
                {
                    "name": "Second",
                    "sequence": 2,
                    "opening_date": "2027-04-01",
                    "due_date": "2027-05-01",
                    "closing_date": "2027-08-01",
                },
            ],
        },
    )
    assert invalid.status_code == 422


def test_only_one_period_can_be_operational(period_workspace) -> None:
    _engine, _user_id, school_id, _other_id, client = period_workspace
    first, second = create_year(client, school_id)
    assert transition(client, first["id"], "open").status_code == 200
    duplicate = transition(client, second["id"], "open")
    assert duplicate.status_code == 409
    assert "current operational period" in duplicate.json()["detail"]


def test_closed_period_rejects_payments_and_requires_owner_reason_to_reopen(
    period_workspace,
) -> None:
    engine, user_id, school_id, _other_id, client = period_workspace
    period = create_year(client, school_id)[0]
    assert transition(client, period["id"], "open").status_code == 200
    assert transition(client, period["id"], "closing").status_code == 200
    assert transition(client, period["id"], "closed").status_code == 200
    with Session(engine) as session:
        person = Person(first_name="Closed", last_name="Learner")
        session.add(person)
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="CLOSED-001",
            gender="female",
        )
        session.add(student)
        session.commit()
        student_id = student.id
    payment = client.post(
        "/api/v1/payments",
        json={
            "school_id": str(school_id),
            "period_id": period["id"],
            "student_id": str(student_id),
            "external_reference": "CLOSED-PAYMENT",
            "channel": "cash",
            "amount": 1000,
        },
    )
    assert payment.status_code == 409
    assert "closed" in payment.json()["detail"]
    assert transition(client, period["id"], "open").status_code == 422
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        assert membership is not None
        membership.role = "bursar"
        session.commit()
    assert transition(client, period["id"], "open", "Correction").status_code == 403


def test_preclose_checklist_blocks_then_routes_financial_controls(period_workspace) -> None:
    engine, user_id, school_id, _other_id, client = period_workspace
    period = create_year(client, school_id)[0]
    period_id = uuid.UUID(period["id"])
    assert transition(client, period["id"], "open").status_code == 200
    assert transition(client, period["id"], "closing").status_code == 200
    with Session(engine) as session:
        person = Person(first_name="Close", last_name="Control")
        session.add(person)
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="CLOSE-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        payment = Payment(
            school_id=school_id,
            period_id=period_id,
            receipt_no="CLOSE-R-001",
            external_reference="CLOSE-P-001",
            channel="cash",
            amount=Decimal("100000"),
            transaction_type="receipt",
            created_by="cashier@example.com",
        )
        bank_payment = Payment(
            school_id=school_id,
            period_id=period_id,
            receipt_no="CLOSE-R-002",
            external_reference="CLOSE-P-002",
            channel="bank_transfer",
            amount=Decimal("45000"),
            transaction_type="receipt",
            created_by="owner@example.com",
        )
        statement_import = StatementImport(
            school_id=school_id,
            period_id=period_id,
            file_name="close.csv",
            source_type="bank",
            content_hash="a" * 64,
            idempotency_key="close-import-001",
            row_count=2,
            total_amount=Decimal("100000"),
            imported_by="owner@example.com",
        )
        session.add_all([payment, bank_payment, statement_import])
        session.flush()
        allocation = PaymentAllocation(
            payment_id=payment.id,
            student_id=student.id,
            allocation_type="unallocated",
            amount=payment.amount,
        )
        statement = StatementTransaction(
            import_id=statement_import.id,
            school_id=school_id,
            period_id=period_id,
            transaction_date=date(2027, 3, 1),
            source_reference="CLOSE-BANK-001",
            description="Unresolved closing receipt",
            amount=Decimal("50000"),
            channel="bank",
            status="unmatched",
        )
        reconciled_statement = StatementTransaction(
            import_id=statement_import.id,
            school_id=school_id,
            period_id=period_id,
            transaction_date=date(2027, 3, 1),
            source_reference="CLOSE-BANK-002",
            description="Linked receipt with a control difference",
            amount=Decimal("50000"),
            channel="bank",
            status="reconciled",
            payment_id=bank_payment.id,
        )
        batch = CashierCollectionBatch(
            school_id=school_id,
            period_id=period_id,
            business_date=date(2027, 3, 1),
            cashier_actor="cashier@example.com",
            status="open",
            expected_cash=Decimal("100000"),
        )
        session.add_all([allocation, statement, reconciled_statement, batch])
        session.commit()
        ids = {
            "payment": payment.id,
            "bank_payment": bank_payment.id,
            "student": student.id,
            "allocation": allocation.id,
            "statement": statement.id,
            "batch": batch.id,
        }

    readiness = client.get(f"/api/v1/academic-periods/{period['id']}/close-readiness")
    assert readiness.status_code == 200, readiness.text
    payload = readiness.json()
    assert payload["ready_to_close"] is False
    blockers = {item["code"]: item for item in payload["controls"] if item["status"] == "blocked"}
    assert set(blockers) == {
        "reconciliation_items",
        "reconciliation_variance",
        "cash_up_batches",
        "unbatched_cash",
        "payment_allocation_balance",
        "unallocated_credit",
    }
    assert blockers["reconciliation_items"]["action_href"] == "/reconciliation"
    assert blockers["unallocated_credit"]["action_href"] == "/payments"
    blocked_close = transition(client, period["id"], "closed")
    assert blocked_close.status_code == 409
    assert blocked_close.json()["detail"]["blocker_count"] == 6
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()
    assert client.get(f"/api/v1/academic-periods/{period['id']}/close-readiness").status_code == 200
    assert transition(client, period["id"], "closed").status_code == 403
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "owner"
        session.commit()

    with Session(engine) as session:
        session.get(StatementTransaction, ids["statement"]).status = "rejected"
        session.get(PaymentAllocation, ids["allocation"]).allocation_type = "fees"
        session.get(Payment, ids["bank_payment"]).amount = Decimal("50000")
        session.add(
            PaymentAllocation(
                payment_id=ids["bank_payment"],
                student_id=ids["student"],
                allocation_type="fees",
                amount=Decimal("50000"),
            )
        )
        batch = session.get(CashierCollectionBatch, ids["batch"])
        batch.status = "signed_off"
        batch.counted_cash = Decimal("99000")
        batch.variance = Decimal("-1000")
        batch.deposit_amount = Decimal("98000")
        batch.deposit_reference = "DEP-CLOSE-001"
        batch.supervisor_note = "Approved documented count and deposit difference"
        batch.signed_off_by = "owner@example.com"
        session.add(
            CashierBatchPayment(
                batch_id=batch.id,
                payment_id=ids["payment"],
                amount=Decimal("100000"),
            )
        )
        session.commit()

    ready = client.get(f"/api/v1/academic-periods/{period['id']}/close-readiness")
    assert ready.status_code == 200, ready.text
    result = ready.json()
    assert result["ready_to_close"] is True
    assert result["blocker_count"] == 0
    assert result["warning_count"] == 1
    warning = next(item for item in result["controls"] if item["status"] == "warning")
    assert warning["code"] == "approved_variances"
    assert transition(client, period["id"], "closed").status_code == 200


def test_controlled_close_is_atomic_idempotent_and_historically_stable(
    period_workspace,
) -> None:
    engine, user_id, school_id, _other_id, client = period_workspace
    first, _second = create_year(client, school_id)
    period_id = uuid.UUID(first["id"])
    assert transition(client, first["id"], "open").status_code == 200
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary Seven",
            level="primary",
            sort_order=7,
        )
        person = Person(first_name="Snapshot", last_name="Learner")
        session.add_all([academic_class, person])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="SNAP-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        session.add(
            Enrollment(
                student_id=student.id,
                class_id=academic_class.id,
                period_id=period_id,
                academic_year=2027,
                term=1,
            )
        )
        payment = Payment(
            school_id=school_id,
            period_id=period_id,
            receipt_no="SNAP-R-001",
            external_reference="SNAP-P-001",
            channel="bank_transfer",
            amount=Decimal("200"),
            created_by="owner@example.com",
        )
        session.add(payment)
        session.flush()
        session.add_all(
            [
                PaymentAllocation(
                    payment_id=payment.id,
                    student_id=student.id,
                    allocation_type="fees",
                    amount=Decimal("200"),
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=period_id,
                    student_id=student.id,
                    entry_type="opening_balance",
                    amount=Decimal("100"),
                    reference="OPENING-SNAP",
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=period_id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("500"),
                    reference="FEE-SNAP",
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=period_id,
                    student_id=student.id,
                    entry_type="discount",
                    amount=Decimal("-50"),
                    reference="DISCOUNT-SNAP",
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=period_id,
                    student_id=student.id,
                    entry_type="payment",
                    amount=Decimal("-200"),
                    reference="PAYMENT-SNAP",
                    payment_id=payment.id,
                ),
            ]
        )
        session.commit()
        student_id = student.id
    assert transition(client, first["id"], "closing").status_code == 200
    closed = transition(client, first["id"], "closed")
    assert closed.status_code == 200, closed.text
    close = closed.json()["close_summary"]
    assert closed.json()["idempotent_replay"] is False
    assert close["learner_count"] == 1
    assert Decimal(close["opening_balance"]) == Decimal("100")
    assert Decimal(close["net_assessed"]) == Decimal("450")
    assert Decimal(close["net_collected"]) == Decimal("200")
    assert Decimal(close["period_activity"]) == Decimal("250")
    assert Decimal(close["closing_balance"]) == Decimal("350")
    assert Decimal(close["outstanding"]) == Decimal("350")
    assert Decimal(close["credit_balance"]) == Decimal("0")
    assert len(close["snapshot_hash"]) == 64

    replay = transition(client, first["id"], "closed")
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["close_summary"]["id"] == close["id"]
    assert replay.json()["close_summary"]["snapshot_hash"] == close["snapshot_hash"]
    summary = client.get(
        f"/api/v1/academic-periods/{first['id']}/close-summary?include_learners=true"
    )
    assert summary.status_code == 200, summary.text
    learner = summary.json()["learners"][0]
    assert learner["student_id"] == str(student_id)
    assert learner["admission_no"] == "SNAP-001"
    assert learner["class_name"] == "Primary Seven"
    assert Decimal(learner["closing_balance"]) == Decimal("350")
    assert transition(client, first["id"], "open", "Correction required").status_code == 409

    with Session(engine) as session:
        assert session.scalar(select(func.count(PeriodClose.id))) == 1
        assert session.scalar(select(func.count(PeriodCloseLearner.id))) == 1
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "period_close",
                AuditEvent.entity_id == uuid.UUID(close["id"]),
            )
        )
        assert event is not None and event.actor == "owner@example.com"
        session.add(
            LedgerEntry(
                school_id=school_id,
                period_id=period_id,
                student_id=student_id,
                entry_type="late_test_change",
                amount=Decimal("999"),
                reference="SQLITE-HISTORY-PROBE",
            )
        )
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()
    stable = client.get(f"/api/v1/academic-periods/{first['id']}/close-summary")
    assert stable.status_code == 200
    assert Decimal(stable.json()["closing_balance"]) == Decimal("350")
    assert stable.json()["snapshot_hash"] == close["snapshot_hash"]
    assert client.get(f"/api/v1/academic-periods/{first['id']}/close-summary").status_code == 200
    assert client.get(f"/api/v1/academic-periods/{uuid.uuid4()}/close-summary").status_code == 409
    assert transition(client, first["id"], "closed").status_code == 403


def test_close_snapshot_rolls_back_when_snapshot_creation_fails(
    period_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _user_id, school_id, other_id, client = period_workspace
    period = create_year(client, school_id)[0]
    assert transition(client, period["id"], "open").status_code == 200
    assert transition(client, period["id"], "closing").status_code == 200
    original = periods_module._create_period_close

    def fail_after_snapshot(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected close failure")

    monkeypatch.setattr(periods_module, "_create_period_close", fail_after_snapshot)
    with pytest.raises(RuntimeError, match="injected close failure"):
        transition(client, period["id"], "closed")
    with Session(engine) as session:
        stored_period = session.get(periods_module.AcademicPeriod, uuid.UUID(period["id"]))
        assert stored_period.status == "closing"
        assert session.scalar(select(func.count(PeriodClose.id))) == 0
        assert session.scalar(select(func.count(PeriodCloseLearner.id))) == 0
        assert (
            session.scalar(
                select(func.count(AuditEvent.id)).where(AuditEvent.entity_type == "period_close")
            )
            == 0
        )


def test_balance_carry_forward_posts_debt_and_credit_once(period_workspace) -> None:
    engine, user_id, school_id, _other_id, client = period_workspace
    first, second = create_year(client, school_id)
    source_id = uuid.UUID(first["id"])
    destination_id = uuid.UUID(second["id"])
    assert transition(client, first["id"], "open").status_code == 200
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary Six",
            level="primary",
            sort_order=6,
        )
        debt_person = Person(first_name="Debt", last_name="Learner")
        credit_person = Person(first_name="Credit", last_name="Learner")
        session.add_all([academic_class, debt_person, credit_person])
        session.flush()
        debt_student = Student(
            school_id=school_id,
            person_id=debt_person.id,
            admission_no="CARRY-DEBT",
            gender="male",
        )
        credit_student = Student(
            school_id=school_id,
            person_id=credit_person.id,
            admission_no="CARRY-CREDIT",
            gender="female",
        )
        session.add_all([debt_student, credit_student])
        session.flush()
        session.add_all(
            [
                Enrollment(
                    student_id=debt_student.id,
                    class_id=academic_class.id,
                    period_id=source_id,
                    academic_year=2027,
                    term=1,
                ),
                Enrollment(
                    student_id=credit_student.id,
                    class_id=academic_class.id,
                    period_id=source_id,
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=source_id,
                    student_id=debt_student.id,
                    entry_type="fee_charge",
                    amount=Decimal("350"),
                    reference="CARRY-DEBT-SOURCE",
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=source_id,
                    student_id=credit_student.id,
                    entry_type="sponsorship_credit",
                    amount=Decimal("-75"),
                    reference="CARRY-CREDIT-SOURCE",
                ),
            ]
        )
        session.commit()
        debt_student_id = debt_student.id
        credit_student_id = credit_student.id

    assert transition(client, first["id"], "closing").status_code == 200
    close_response = transition(client, first["id"], "closed")
    assert close_response.status_code == 200, close_response.text
    source_hash = close_response.json()["close_summary"]["snapshot_hash"]

    preview = client.get(
        f"/api/v1/academic-periods/{first['id']}/carry-forward-preview",
        params={"destination_period_id": second["id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["ready_to_post"] is True
    assert preview.json()["learner_count"] == 2
    assert Decimal(preview.json()["debt_total"]) == Decimal("350")
    assert Decimal(preview.json()["credit_total"]) == Decimal("75")
    assert Decimal(preview.json()["net_balance"]) == Decimal("275")

    posted = client.post(
        f"/api/v1/academic-periods/{first['id']}/carry-forward",
        json={
            "destination_period_id": second["id"],
            "idempotency_key": "carry-2027-term-1-to-2",
        },
    )
    assert posted.status_code == 201, posted.text
    result = posted.json()
    assert result["idempotent_replay"] is False
    assert result["source_snapshot_hash"] == source_hash
    assert result["learner_count"] == 2
    assert {Decimal(line["amount"]) for line in result["lines"]} == {
        Decimal("350"),
        Decimal("-75"),
    }

    replay = client.post(
        f"/api/v1/academic-periods/{first['id']}/carry-forward",
        json={
            "destination_period_id": second["id"],
            "idempotency_key": "a-different-safe-retry-key",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["id"] == result["id"]

    opened_destination = transition(client, second["id"], "open")
    assert opened_destination.status_code == 200, opened_destination.text
    historical_close = client.get(
        f"/api/v1/academic-periods/{first['id']}/close-summary?include_learners=true"
    )
    assert historical_close.status_code == 200, historical_close.text
    assert historical_close.json()["snapshot_hash"] == source_hash
    assert Decimal(historical_close.json()["closing_balance"]) == Decimal("275")
    assert {
        Decimal(learner["closing_balance"])
        for learner in historical_close.json()["learners"]
    } == {Decimal("350"), Decimal("-75")}

    with Session(engine) as session:
        assert session.scalar(select(func.count(BalanceCarryForward.id))) == 1
        assert session.scalar(select(func.count(BalanceCarryForwardLine.id))) == 2
        carried_entries = session.scalars(
            select(LedgerEntry).where(
                LedgerEntry.period_id == destination_id,
                LedgerEntry.entry_type == "carried_balance",
            )
        ).all()
        assert len(carried_entries) == 2
        destination = session.get(AcademicPeriod, destination_id)
        destination_totals = load_learner_financial_totals(session, period=destination)
        debt_totals = destination_totals[debt_student_id]
        credit_totals = destination_totals[credit_student_id]
        assert debt_totals.opening_balance == Decimal("350")
        assert debt_totals.closing_balance == Decimal("350")
        assert credit_totals.opening_balance == Decimal("-75")
        assert credit_totals.closing_balance == Decimal("-75")
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "balance_carry_forward",
                AuditEvent.entity_id == uuid.UUID(result["id"]),
            )
        )
        assert event is not None and event.actor == "owner@example.com"
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()

    summary = client.get(f"/api/v1/academic-periods/{first['id']}/carry-forward")
    assert summary.status_code == 200
    assert summary.json()["source_snapshot_hash"] == source_hash
    assert (
        client.post(
            f"/api/v1/academic-periods/{first['id']}/carry-forward",
            json={
                "destination_period_id": second["id"],
                "idempotency_key": "auditor-cannot-post",
            },
        ).status_code
        == 403
    )


def test_balance_carry_rejects_conflicting_opening_and_skipped_period(
    period_workspace,
) -> None:
    engine, _user_id, school_id, other_id, client = period_workspace
    first, second = create_year(client, school_id)
    assert transition(client, first["id"], "open").status_code == 200
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary Five",
            level="primary",
            sort_order=5,
        )
        person = Person(first_name="Opening", last_name="Conflict")
        session.add_all([academic_class, person])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="OPENING-CONFLICT",
            gender="female",
        )
        session.add(student)
        session.flush()
        session.add_all(
            [
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=uuid.UUID(first["id"]),
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=uuid.UUID(first["id"]),
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("120"),
                    reference="CARRY-CONFLICT-SOURCE",
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=uuid.UUID(second["id"]),
                    student_id=student.id,
                    entry_type="opening_balance",
                    amount=Decimal("100"),
                    reference="EXISTING-OPENING",
                ),
            ]
        )
        future_year = AcademicYear(
            school_id=school_id,
            name="2028 Academic Year",
            year=2028,
            start_date=date(2028, 1, 10),
            end_date=date(2028, 12, 5),
            status="draft",
        )
        future_period = AcademicPeriod(
            school_id=school_id,
            name="Term 1",
            sequence=1,
            opening_date=date(2028, 1, 10),
            due_date=date(2028, 2, 10),
            closing_date=date(2028, 4, 20),
            status="draft",
        )
        future_year.periods = [future_period]
        other_year = AcademicYear(
            school_id=other_id,
            name="Other school 2027",
            year=2027,
            start_date=date(2027, 1, 10),
            end_date=date(2027, 12, 5),
            status="draft",
        )
        other_period = AcademicPeriod(
            school_id=other_id,
            name="Term 2",
            sequence=2,
            opening_date=date(2027, 5, 20),
            due_date=date(2027, 6, 10),
            closing_date=date(2027, 8, 20),
            status="draft",
        )
        other_year.periods = [other_period]
        session.add_all([future_year, other_year])
        session.commit()
        future_period_id = future_period.id
        other_period_id = other_period.id

    assert transition(client, first["id"], "closing").status_code == 200
    assert transition(client, first["id"], "closed").status_code == 200
    skipped = client.get(
        f"/api/v1/academic-periods/{first['id']}/carry-forward-preview",
        params={"destination_period_id": str(future_period_id)},
    )
    assert skipped.status_code == 422
    cross_school = client.get(
        f"/api/v1/academic-periods/{first['id']}/carry-forward-preview",
        params={"destination_period_id": str(other_period_id)},
    )
    assert cross_school.status_code == 409
    assert "other" not in cross_school.text.lower()
    preview = client.get(
        f"/api/v1/academic-periods/{first['id']}/carry-forward-preview",
        params={"destination_period_id": second["id"]},
    )
    assert preview.status_code == 200
    assert preview.json()["ready_to_post"] is False
    assert preview.json()["conflicting_opening_count"] == 1
    blocked = client.post(
        f"/api/v1/academic-periods/{first['id']}/carry-forward",
        json={
            "destination_period_id": second["id"],
            "idempotency_key": "carry-conflicting-opening",
        },
    )
    assert blocked.status_code == 409
    with Session(engine) as session:
        assert session.scalar(select(func.count(BalanceCarryForward.id))) == 0
        assert session.scalar(select(func.count(BalanceCarryForwardLine.id))) == 0
        assert (
            session.scalar(
                select(func.count(LedgerEntry.id)).where(
                    LedgerEntry.entry_type == "carried_balance"
                )
            )
            == 0
        )


def test_balance_carry_rolls_back_after_posting_failure(
    period_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    first, second = create_year(client, school_id)
    assert transition(client, first["id"], "open").status_code == 200
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary Four",
            level="primary",
            sort_order=4,
        )
        person = Person(first_name="Rollback", last_name="Learner")
        session.add_all([academic_class, person])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="CARRY-ROLLBACK",
            gender="male",
        )
        session.add(student)
        session.flush()
        session.add_all(
            [
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=uuid.UUID(first["id"]),
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=uuid.UUID(first["id"]),
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("90"),
                    reference="CARRY-ROLLBACK-SOURCE",
                ),
            ]
        )
        session.commit()
    assert transition(client, first["id"], "closing").status_code == 200
    assert transition(client, first["id"], "closed").status_code == 200
    original = periods_module._create_balance_carry

    def fail_after_posting(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected carry failure")

    monkeypatch.setattr(periods_module, "_create_balance_carry", fail_after_posting)
    with pytest.raises(RuntimeError, match="injected carry failure"):
        client.post(
            f"/api/v1/academic-periods/{first['id']}/carry-forward",
            json={
                "destination_period_id": second["id"],
                "idempotency_key": "carry-rollback-test",
            },
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count(BalanceCarryForward.id))) == 0
        assert session.scalar(select(func.count(BalanceCarryForwardLine.id))) == 0
        assert (
            session.scalar(
                select(func.count(LedgerEntry.id)).where(
                    LedgerEntry.entry_type == "carried_balance"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_type == "balance_carry_forward"
                )
            )
            == 0
        )


def prepare_rollover(
    engine, client: TestClient, school_id: uuid.UUID, learner_specs: list[tuple[str, str]]
) -> tuple[dict, dict, dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    source = create_single_period_year(client, school_id, 2027)
    destination = create_single_period_year(client, school_id, 2028)
    with Session(engine) as session:
        primary_six = AcademicClass(
            school_id=school_id,
            name="Primary Six",
            level="primary",
            canonical_code="P6",
            sort_order=6,
        )
        primary_seven = AcademicClass(
            school_id=school_id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        session.add_all([primary_six, primary_seven])
        session.flush()
        class_ids = {"P6": primary_six.id, "P7": primary_seven.id}
        student_ids = {}
        for admission_no, class_code in learner_specs:
            person = Person(first_name=admission_no, last_name="Learner")
            session.add(person)
            session.flush()
            student = Student(
                school_id=school_id,
                person_id=person.id,
                admission_no=admission_no,
                gender="female",
            )
            session.add(student)
            session.flush()
            student_ids[admission_no] = student.id
            session.add(
                Enrollment(
                    student_id=student.id,
                    class_id=class_ids[class_code],
                    period_id=uuid.UUID(source["id"]),
                    academic_year=2027,
                    term=1,
                )
            )
        session.commit()
    assert transition(client, source["id"], "open").status_code == 200
    assert transition(client, source["id"], "closing").status_code == 200
    assert transition(client, source["id"], "closed").status_code == 200
    carry = client.post(
        f"/api/v1/academic-periods/{source['id']}/carry-forward",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": f"carry:{source['id']}:{destination['id']}",
        },
    )
    assert carry.status_code == 201, carry.text
    return source, destination, student_ids, class_ids


def test_learner_rollover_applies_all_decisions_once(period_workspace) -> None:
    engine, user_id, school_id, _other_id, client = period_workspace
    source, destination, students, classes = prepare_rollover(
        engine,
        client,
        school_id,
        [
            ("PROMOTE", "P6"),
            ("REPEAT", "P6"),
            ("HOLD", "P6"),
            ("COMPLETE", "P7"),
            ("DEPART", "P6"),
        ],
    )
    preview = client.get(
        "/api/v1/learner-rollovers/preview",
        params={
            "source_period_id": source["id"],
            "destination_period_id": destination["id"],
        },
    )
    assert preview.status_code == 200, preview.text
    suggestions = {
        item["admission_no"]: item["suggested_decision"] for item in preview.json()["learners"]
    }
    assert suggestions["PROMOTE"] == "promote"
    assert suggestions["COMPLETE"] == "complete"
    decisions = [
        {
            "student_id": str(students["PROMOTE"]),
            "decision": "promote",
            "target_class_id": str(classes["P7"]),
        },
        {
            "student_id": str(students["REPEAT"]),
            "decision": "repeat",
            "target_class_id": str(classes["P6"]),
        },
        {
            "student_id": str(students["HOLD"]),
            "decision": "hold",
            "reason": "Awaiting guardian confirmation",
        },
        {"student_id": str(students["COMPLETE"]), "decision": "complete"},
        {
            "student_id": str(students["DEPART"]),
            "decision": "depart",
            "reason": "Family relocation",
        },
    ]
    posted = client.post(
        f"/api/v1/learner-rollovers/{source['id']}",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "rollover-2027-to-2028",
            "decisions": decisions,
        },
    )
    assert posted.status_code == 201, posted.text
    result = posted.json()
    assert result["candidate_count"] == 5
    assert result["placed_count"] == 2
    assert result["held_count"] == result["completed_count"] == result["departed_count"] == 1
    replay = client.post(
        f"/api/v1/learner-rollovers/{source['id']}",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "another-rollover-retry",
            "decisions": decisions,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == result["id"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(LearnerRollover.id))) == 1
        assert session.scalar(select(func.count(LearnerRolloverLine.id))) == 5
        destination_ids = set(
            session.scalars(
                select(Enrollment.student_id).where(
                    Enrollment.period_id == uuid.UUID(destination["id"])
                )
            ).all()
        )
        assert destination_ids == {students["PROMOTE"], students["REPEAT"]}
        assert session.get(Student, students["HOLD"]).status == "active"
        assert session.get(Student, students["COMPLETE"]).status == "completed"
        assert session.get(Student, students["DEPART"]).status == "withdrawn"
        assert (
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_type == "student_rollover"
                )
            )
            == 5
        )
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()
    assert client.get(f"/api/v1/learner-rollovers/{source['id']}").status_code == 200
    assert (
        client.post(
            f"/api/v1/learner-rollovers/{source['id']}",
            json={
                "destination_period_id": destination["id"],
                "idempotency_key": "auditor-rollover-denied",
                "decisions": decisions,
            },
        ).status_code
        == 403
    )


def test_learner_rollover_rejects_incomplete_or_invalid_review(period_workspace) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    source, destination, students, classes = prepare_rollover(
        engine, client, school_id, [("ONE", "P6"), ("TWO", "P6")]
    )
    incomplete = client.post(
        f"/api/v1/learner-rollovers/{source['id']}",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "incomplete-rollover",
            "decisions": [
                {
                    "student_id": str(students["ONE"]),
                    "decision": "promote",
                    "target_class_id": str(classes["P7"]),
                }
            ],
        },
    )
    assert incomplete.status_code == 422
    invalid = client.post(
        f"/api/v1/learner-rollovers/{source['id']}",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "invalid-rollover",
            "decisions": [
                {
                    "student_id": str(students["ONE"]),
                    "decision": "repeat",
                    "target_class_id": str(classes["P7"]),
                },
                {
                    "student_id": str(students["TWO"]),
                    "decision": "promote",
                    "target_class_id": str(classes["P7"]),
                },
            ],
        },
    )
    assert invalid.status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(func.count(LearnerRollover.id))) == 0
        assert session.scalar(select(func.count(LearnerRolloverLine.id))) == 0


def test_learner_rollover_rolls_back_partial_placement(
    period_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    source, destination, students, classes = prepare_rollover(
        engine, client, school_id, [("ROLLBACK", "P6")]
    )

    def fail_fee_assignment(*_args, **_kwargs):
        raise RuntimeError("injected rollover failure")

    monkeypatch.setattr(rollover_module, "assign_published_general_fee", fail_fee_assignment)
    with pytest.raises(RuntimeError, match="injected rollover failure"):
        client.post(
            f"/api/v1/learner-rollovers/{source['id']}",
            json={
                "destination_period_id": destination["id"],
                "idempotency_key": "rollback-rollover",
                "decisions": [
                    {
                        "student_id": str(students["ROLLBACK"]),
                        "decision": "promote",
                        "target_class_id": str(classes["P7"]),
                    }
                ],
            },
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count(LearnerRollover.id))) == 0
        assert session.scalar(select(func.count(LearnerRolloverLine.id))) == 0
        assert (
            session.scalar(
                select(func.count(Enrollment.id)).where(
                    Enrollment.period_id == uuid.UUID(destination["id"])
                )
            )
            == 0
        )
        assert session.get(Student, students["ROLLBACK"]).status == "active"


def test_day_care_classless_learner_continues_with_close_evidence(period_workspace) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    source = create_single_period_year(client, school_id, 2027)
    destination = create_single_period_year(client, school_id, 2028)
    with Session(engine) as session:
        person = Person(first_name="Daycare", last_name="Learner")
        session.add_all(
            [
                SchoolProgramme(
                    school_id=school_id,
                    programme_code="day_care",
                    display_name="Day care",
                    sort_order=1,
                ),
                person,
            ]
        )
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="DAYCARE-ONE",
            gender="female",
        )
        session.add(student)
        session.commit()
        student_id = student.id
    assert transition(client, source["id"], "open").status_code == 200
    assert transition(client, source["id"], "closing").status_code == 200
    closed = transition(client, source["id"], "closed")
    assert closed.status_code == 200
    assert closed.json()["close_summary"]["learner_count"] == 1
    assert (
        client.post(
            f"/api/v1/academic-periods/{source['id']}/carry-forward",
            json={
                "destination_period_id": destination["id"],
                "idempotency_key": "daycare-carry-forward",
            },
        ).status_code
        == 201
    )
    preview = client.get(
        "/api/v1/learner-rollovers/preview",
        params={
            "source_period_id": source["id"],
            "destination_period_id": destination["id"],
        },
    )
    assert preview.status_code == 200
    learner = preview.json()["learners"][0]
    assert learner["student_id"] == str(student_id)
    assert learner["suggested_decision"] == "continue"
    assert learner["suggested_target_class_id"] is None
    applied = client.post(
        f"/api/v1/learner-rollovers/{source['id']}",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "daycare-rollover",
            "decisions": [
                {
                    "student_id": str(student_id),
                    "decision": "continue",
                    "target_class_id": None,
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["placed_count"] == 1
    assert applied.json()["lines"][0]["enrollment_id"] is None


def prepare_controlled_reopening(period_workspace):
    engine, user_id, school_id, other_id, client = period_workspace
    source, destination = create_year(client, school_id)
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        person = Person(first_name="Correction", last_name="Learner")
        session.add_all([academic_class, person])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="REOPEN-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        session.add_all(
            [
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=uuid.UUID(source["id"]),
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=uuid.UUID(source["id"]),
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("350"),
                    reference="REOPEN-SOURCE-FEE",
                ),
            ]
        )
        session.commit()
        student_id = student.id
    assert transition(client, source["id"], "open").status_code == 200
    assert transition(client, source["id"], "closing").status_code == 200
    closed = transition(client, source["id"], "closed")
    assert closed.status_code == 200, closed.text
    carry = client.post(
        f"/api/v1/academic-periods/{source['id']}/carry-forward",
        json={
            "destination_period_id": destination["id"],
            "idempotency_key": "reopening-source-carry",
        },
    )
    assert carry.status_code == 201, carry.text
    return (
        engine,
        user_id,
        school_id,
        other_id,
        client,
        source,
        destination,
        student_id,
        closed.json(),
    )


def test_controlled_reopening_preserves_close_and_propagates_delta(period_workspace) -> None:
    (
        engine,
        user_id,
        _school_id,
        _other_id,
        client,
        source,
        destination,
        student_id,
        closed,
    ) = prepare_controlled_reopening(period_workspace)
    original_hash = closed["close_summary"]["snapshot_hash"]
    preview = client.get(f"/api/v1/academic-periods/{source['id']}/reopening-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"] is True
    assert preview.json()["next_snapshot_version"] == 2
    assert preview.json()["effective_snapshot_hash"] == original_hash
    assert Decimal(preview.json()["learners"][0]["closing_balance"]) == Decimal("350")

    payload = {
        "idempotency_key": "reopen-term-one-case-001",
        "reason": "A verified omitted examination charge must be recorded",
        "corrections": [
            {
                "student_id": str(student_id),
                "correction_type": "charge",
                "amount": "100.00",
                "reason": "Examination charge omitted from the published bill",
            }
        ],
    }
    applied = client.post(
        f"/api/v1/academic-periods/{source['id']}/controlled-reopening",
        json=payload,
    )
    assert applied.status_code == 201, applied.text
    result = applied.json()
    assert result["snapshot_version"] == 2
    assert result["original_snapshot_hash"] == original_hash
    assert result["prior_snapshot_hash"] == original_hash
    assert result["revised_snapshot_hash"] != original_hash
    assert Decimal(result["net_adjustment"]) == Decimal("100")
    assert Decimal(result["closing_balance"]) == Decimal("450")
    assert result["corrections"][0]["propagated"] is True

    replay = client.post(
        f"/api/v1/academic-periods/{source['id']}/controlled-reopening",
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["id"] == result["id"]
    original = client.get(f"/api/v1/academic-periods/{source['id']}/close-summary")
    assert original.status_code == 200
    assert original.json()["snapshot_hash"] == original_hash
    assert Decimal(original.json()["closing_balance"]) == Decimal("350")

    with Session(engine) as session:
        assert session.scalar(select(func.count(PeriodReopening.id))) == 1
        assert session.scalar(select(func.count(PeriodReopeningCorrection.id))) == 1
        assert session.scalar(select(func.count(PeriodReopeningLearner.id))) == 1
        source_delta = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.period_id == uuid.UUID(source["id"]),
                LedgerEntry.entry_type == "period_correction_charge",
            )
        )
        destination_delta = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.period_id == uuid.UUID(destination["id"]),
                LedgerEntry.entry_type == "carry_correction",
            )
        )
        assert source_delta is not None and source_delta.amount == Decimal("100")
        assert destination_delta is not None and destination_delta.amount == Decimal("100")
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.entity_type == "period_reopening")
        )
        assert event is not None and event.actor == "owner@example.com"
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()
    assert client.get(f"/api/v1/academic-periods/{source['id']}/reopenings").status_code == 200
    denied = client.post(
        f"/api/v1/academic-periods/{source['id']}/controlled-reopening",
        json={**payload, "idempotency_key": "auditor-reopen-denied"},
    )
    assert denied.status_code == 403


def test_controlled_reopening_rejects_invalid_scope_and_rolls_back(
    period_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        engine,
        _user_id,
        school_id,
        _other_id,
        client,
        source,
        _destination,
        _student_id,
        _closed,
    ) = prepare_controlled_reopening(period_workspace)
    with Session(engine) as session:
        person = Person(first_name="Outside", last_name="Snapshot")
        session.add(person)
        session.flush()
        outside = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="OUTSIDE-CLOSE",
            gender="male",
        )
        session.add(outside)
        session.commit()
        outside_id = outside.id
    invalid = client.post(
        f"/api/v1/academic-periods/{source['id']}/controlled-reopening",
        json={
            "idempotency_key": "invalid-reopening-scope",
            "reason": "Attempting an invalid correction outside the sealed register",
            "corrections": [
                {
                    "student_id": str(outside_id),
                    "correction_type": "credit",
                    "amount": "20",
                    "reason": "This learner was not part of the closing evidence",
                }
            ],
        },
    )
    assert invalid.status_code == 422

    def fail_totals(*_args, **_kwargs):
        raise RuntimeError("injected reopening failure")

    monkeypatch.setattr(reopening_module, "aggregate_financial_totals", fail_totals)
    preview = client.get(f"/api/v1/academic-periods/{source['id']}/reopening-preview")
    student_id = preview.json()["learners"][0]["student_id"]
    with pytest.raises(RuntimeError, match="injected reopening failure"):
        client.post(
            f"/api/v1/academic-periods/{source['id']}/controlled-reopening",
            json={
                "idempotency_key": "rollback-reopening-case",
                "reason": "A verified correction used to exercise atomic rollback",
                "corrections": [
                    {
                        "student_id": student_id,
                        "correction_type": "credit",
                        "amount": "25",
                        "reason": "Verified duplicate assessment should be credited",
                    }
                ],
            },
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count(PeriodReopening.id))) == 0
        assert session.scalar(select(func.count(PeriodReopeningCorrection.id))) == 0
        assert session.scalar(select(func.count(PeriodReopeningLearner.id))) == 0
        assert (
            session.scalar(
                select(func.count(LedgerEntry.id)).where(
                    LedgerEntry.entry_type.in_(
                        ("period_correction_charge", "period_correction_credit", "carry_correction")
                    )
                )
            )
            == 0
        )


def test_period_with_enrollment_activity_cannot_be_deleted(period_workspace) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    period = create_year(client, school_id)[0]
    with Session(engine) as session:
        academic_class = AcademicClass(
            school_id=school_id,
            name="Primary One",
            level="primary",
            sort_order=1,
        )
        person = Person(first_name="Term", last_name="Learner")
        session.add_all([academic_class, person])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=person.id,
            admission_no="TERM-001",
            gender="male",
        )
        session.add(student)
        session.flush()
        session.add(
            Enrollment(
                student_id=student.id,
                class_id=academic_class.id,
                period_id=uuid.UUID(period["id"]),
                academic_year=2027,
                term=1,
            )
        )
        session.commit()
    response = client.delete(f"/api/v1/academic-periods/{period['id']}")
    assert response.status_code == 409
    assert "activity" in response.json()["detail"]


def test_selected_period_filters_core_bursar_registers(period_workspace) -> None:
    engine, _user_id, school_id, _other_id, client = period_workspace
    first, second = create_year(client, school_id)
    first_id, second_id = uuid.UUID(first["id"]), uuid.UUID(second["id"])
    with Session(engine) as session:
        first_class = AcademicClass(
            school_id=school_id, name="Primary One", level="primary", sort_order=1
        )
        second_class = AcademicClass(
            school_id=school_id, name="Primary Two", level="primary", sort_order=2
        )
        learner = Person(first_name="Period", last_name="Learner")
        guardian = Person(first_name="Period", last_name="Guardian", phone="0700000000")
        session.add_all([first_class, second_class, learner, guardian])
        session.flush()
        student = Student(
            school_id=school_id,
            person_id=learner.id,
            admission_no="PERIOD-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        session.add(
            GuardianLink(
                student_id=student.id,
                person_id=guardian.id,
                relationship="guardian",
                is_primary=True,
            )
        )
        session.add_all(
            [
                Enrollment(
                    student_id=student.id,
                    class_id=first_class.id,
                    period_id=first_id,
                    academic_year=2027,
                    term=1,
                ),
                Enrollment(
                    student_id=student.id,
                    class_id=second_class.id,
                    period_id=second_id,
                    academic_year=2027,
                    term=2,
                ),
            ]
        )
        first_fee = FeeStructure(
            school_id=school_id,
            class_id=first_class.id,
            period_id=first_id,
            name="First term fees",
            academic_year=2027,
            term=1,
            total_amount=Decimal("1000"),
        )
        second_fee = FeeStructure(
            school_id=school_id,
            class_id=second_class.id,
            period_id=second_id,
            name="Second term fees",
            academic_year=2027,
            term=2,
            total_amount=Decimal("2000"),
        )
        session.add_all([first_fee, second_fee])
        session.flush()
        session.add_all(
            [
                InstallmentRule(
                    fee_structure_id=first_fee.id,
                    name="Term 1 due",
                    amount=first_fee.total_amount,
                    due_date=date(2027, 2, 10),
                    sort_order=1,
                ),
                InstallmentRule(
                    fee_structure_id=second_fee.id,
                    name="Term 2 due",
                    amount=second_fee.total_amount,
                    due_date=date(2027, 6, 15),
                    sort_order=1,
                ),
                StudentFeeAssignment(
                    id=(first_assignment_id := uuid.uuid4()),
                    student_id=student.id,
                    fee_structure_id=first_fee.id,
                    amount=first_fee.total_amount,
                ),
                StudentFeeAssignment(
                    id=(second_assignment_id := uuid.uuid4()),
                    student_id=student.id,
                    fee_structure_id=second_fee.id,
                    amount=second_fee.total_amount,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=first_id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=first_fee.total_amount,
                    reference=f"FEE:{first_assignment_id}",
                    fee_assignment_id=first_assignment_id,
                ),
                LedgerEntry(
                    school_id=school_id,
                    period_id=second_id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=second_fee.total_amount,
                    reference=f"FEE:{second_assignment_id}",
                    fee_assignment_id=second_assignment_id,
                ),
                Requirement(
                    school_id=school_id,
                    period_id=first_id,
                    name="First term item",
                    code="FIRST",
                    requirement_type="bring_item",
                    academic_year=2027,
                    term=1,
                    amount=Decimal("0"),
                    quantity=Decimal("1"),
                ),
                Requirement(
                    school_id=school_id,
                    period_id=second_id,
                    name="Second term item",
                    code="SECOND",
                    requirement_type="bring_item",
                    academic_year=2027,
                    term=2,
                    amount=Decimal("0"),
                    quantity=Decimal("1"),
                ),
            ]
        )
        for index, (period_id, amount) in enumerate(
            ((first_id, Decimal("400")), (second_id, Decimal("700"))), start=1
        ):
            payment = Payment(
                school_id=school_id,
                period_id=period_id,
                receipt_no=f"PERIOD-R-{index}",
                external_reference=f"PERIOD-P-{index}",
                channel="cash",
                amount=amount,
            )
            session.add(payment)
            session.flush()
            session.add_all(
                [
                    PaymentAllocation(payment_id=payment.id, student_id=student.id, amount=amount),
                    StellarAnchor(
                        payment_id=payment.id,
                        commitment_hash=f"{index:064x}",
                        status="pending",
                    ),
                ]
            )
        session.commit()

    first_query = f"school_id={school_id}&period_id={first_id}"
    second_query = f"school_id={school_id}&period_id={second_id}"
    first_fees = client.get(f"/api/v1/fee-structures?{first_query}").json()
    second_fees = client.get(f"/api/v1/fee-structures?{second_query}").json()
    assert first_fees[0]["name"] == "First term fees"
    assert second_fees[0]["name"] == "Second term fees"
    assert client.get(f"/api/v1/requirements?{first_query}").json()[0]["code"] == "FIRST"
    assert client.get(f"/api/v1/requirements?{second_query}").json()[0]["code"] == "SECOND"
    assert (
        client.get(f"/api/v1/students?{first_query}").json()["items"][0]["class_name"]
        == "Primary One"
    )
    assert (
        client.get(f"/api/v1/students?{second_query}").json()["items"][0]["class_name"]
        == "Primary Two"
    )
    assert client.get(f"/api/v1/payments?{first_query}").json()[0]["amount"] == "400.00"
    assert client.get(f"/api/v1/payments?{second_query}").json()[0]["amount"] == "700.00"
    first_dashboard = client.get(f"/api/v1/dashboard?{first_query}").json()
    second_dashboard = client.get(f"/api/v1/dashboard?{second_query}").json()
    assert first_dashboard["metrics"]["billed"] == 1000.0
    assert second_dashboard["metrics"]["billed"] == 2000.0
    report_dates = "&start_date=2020-01-01&end_date=2100-12-31"
    first_report = client.get(f"/api/v1/reports/collections?{first_query}{report_dates}").json()
    second_report = client.get(f"/api/v1/reports/collections?{second_query}{report_dates}").json()
    assert first_report["collected"] == 400.0
    assert second_report["collected"] == 700.0
    first_arrears = client.get(f"/api/v1/arrears?{first_query}&as_of=2027-12-31").json()
    second_arrears = client.get(f"/api/v1/arrears?{second_query}&as_of=2027-12-31").json()
    assert Decimal(str(first_arrears["total_overdue"])) == Decimal("600")
    assert Decimal(str(second_arrears["total_overdue"])) == Decimal("1300")
