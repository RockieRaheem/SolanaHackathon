import uuid
from datetime import UTC, date, datetime
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
    BillingAdjustment,
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
    Requirement,
    School,
    SchoolMembership,
    StellarAnchor,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)


@pytest.fixture
def account_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school = School(name="Account School")
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
        first = AcademicPeriod(
            academic_year_id=year.id,
            school_id=school.id,
            name="Term 1",
            sequence=1,
            opening_date=date(2027, 1, 5),
            due_date=date(2027, 2, 1),
            closing_date=date(2027, 4, 20),
            status="closed",
        )
        second = AcademicPeriod(
            academic_year_id=year.id,
            school_id=school.id,
            name="Term 2",
            sequence=2,
            opening_date=date(2027, 5, 20),
            due_date=date(2027, 6, 15),
            closing_date=date(2027, 8, 20),
            status="open",
        )
        primary_six = AcademicClass(
            school_id=school.id, name="Primary Six", level="primary", sort_order=6
        )
        primary_seven = AcademicClass(
            school_id=school.id, name="Primary Seven", level="primary", sort_order=7
        )
        session.add_all([first, second, primary_six, primary_seven])
        session.flush()
        person = Person(first_name="Amina", last_name="Kato")
        guardian = Person(
            first_name="Sarah", last_name="Kato", phone="+256700000001", email="s@example.com"
        )
        private_contact = Person(first_name="Private", last_name="Contact", phone="+256700000002")
        session.add_all([person, guardian, private_contact])
        session.flush()
        student = Student(
            school_id=school.id,
            person_id=person.id,
            admission_no="ACC-001",
            gender="female",
        )
        other_person = Person(first_name="Other", last_name="Learner")
        session.add_all([student, other_person])
        session.flush()
        other_student = Student(
            school_id=other_school.id,
            person_id=other_person.id,
            admission_no="OTHER-001",
            gender="male",
        )
        session.add(other_student)
        session.flush()
        session.add_all(
            [
                GuardianLink(
                    student_id=student.id,
                    person_id=guardian.id,
                    relationship="mother",
                    is_primary=True,
                    can_receive_statements=True,
                ),
                GuardianLink(
                    student_id=student.id,
                    person_id=private_contact.id,
                    relationship="relative",
                    can_receive_statements=False,
                ),
                Enrollment(
                    student_id=student.id,
                    class_id=primary_six.id,
                    period_id=first.id,
                    academic_year=2027,
                    term=1,
                ),
                Enrollment(
                    student_id=student.id,
                    class_id=primary_seven.id,
                    period_id=second.id,
                    academic_year=2027,
                    term=2,
                ),
            ]
        )
        tuition = FeeCategory(
            school_id=school.id,
            name="Tuition",
            code="TUIT",
            category_type="tuition",
            is_required=True,
        )
        uniform = FeeCategory(
            school_id=school.id,
            name="Candidate uniform",
            code="UNIF",
            category_type="uniform",
            is_required=False,
        )
        session.add_all([tuition, uniform])
        session.flush()
        first_plan = FeeStructure(
            school_id=school.id,
            class_id=primary_six.id,
            period_id=first.id,
            name="Term 1 fees",
            academic_year=2027,
            term=1,
            total_amount=Decimal("100"),
            status="published",
        )
        second_plan = FeeStructure(
            school_id=school.id,
            class_id=primary_seven.id,
            period_id=second.id,
            name="P.7 fees and uniform",
            academic_year=2027,
            term=2,
            total_amount=Decimal("200"),
            status="published",
        )
        session.add_all([first_plan, second_plan])
        session.flush()
        session.add_all(
            [
                FeeStructureItem(
                    fee_structure_id=first_plan.id,
                    category_id=tuition.id,
                    amount=Decimal("100"),
                ),
                FeeStructureItem(
                    fee_structure_id=second_plan.id,
                    category_id=tuition.id,
                    amount=Decimal("150"),
                ),
                FeeStructureItem(
                    fee_structure_id=second_plan.id,
                    category_id=uniform.id,
                    amount=Decimal("50"),
                ),
                InstallmentRule(
                    fee_structure_id=second_plan.id,
                    name="Term 2 due",
                    amount=Decimal("200"),
                    due_date=date(2027, 6, 15),
                    sort_order=1,
                ),
            ]
        )
        first_assignment = StudentFeeAssignment(
            student_id=student.id,
            fee_structure_id=first_plan.id,
            amount=Decimal("100"),
        )
        second_assignment = StudentFeeAssignment(
            student_id=student.id,
            fee_structure_id=second_plan.id,
            amount=Decimal("200"),
        )
        session.add_all([first_assignment, second_assignment])
        session.flush()
        requirement = Requirement(
            school_id=school.id,
            period_id=second.id,
            name="Candidate trip",
            code="TRIP",
            requirement_type="school_item",
            academic_year=2027,
            term=2,
            amount=Decimal("30"),
            quantity=Decimal("1"),
            unit="place",
            is_mandatory=False,
            status="published",
        )
        physical = Requirement(
            school_id=school.id,
            period_id=second.id,
            name="National ID copy",
            code="NID",
            requirement_type="document",
            academic_year=2027,
            term=2,
            amount=Decimal("0"),
            quantity=Decimal("1"),
            unit="copy",
            status="published",
        )
        session.add_all([requirement, physical])
        session.flush()
        requirement_assignment = StudentRequirement(
            requirement_id=requirement.id,
            student_id=student.id,
            expected_amount=Decimal("30"),
            expected_quantity=Decimal("1"),
            assigned_at=datetime(2027, 5, 22, tzinfo=UTC),
        )
        physical_assignment = StudentRequirement(
            requirement_id=physical.id,
            student_id=student.id,
            expected_amount=Decimal("0"),
            expected_quantity=Decimal("1"),
            assigned_at=datetime(2027, 5, 23, tzinfo=UTC),
        )
        adjustment = BillingAdjustment(
            school_id=school.id,
            period_id=second.id,
            student_id=student.id,
            adjustment_type="discount",
            amount=Decimal("20"),
            description="Sibling discount",
            reason="Approved sibling policy",
            status="published",
        )
        first_payment = Payment(
            school_id=school.id,
            period_id=first.id,
            receipt_no="ACC-R-1",
            external_reference="ACC-P-1",
            payer_name="Sarah Kato",
            channel="cash",
            amount=Decimal("40"),
            received_at=datetime(2027, 2, 2, tzinfo=UTC),
        )
        second_payment = Payment(
            school_id=school.id,
            period_id=second.id,
            receipt_no="ACC-R-2",
            external_reference="ACC-P-2",
            payer_name="Sarah Kato",
            channel="bank",
            amount=Decimal("100"),
            received_at=datetime(2027, 5, 25, tzinfo=UTC),
        )
        session.add_all(
            [
                requirement_assignment,
                physical_assignment,
                adjustment,
                first_payment,
                second_payment,
            ]
        )
        session.flush()
        session.add_all(
            [
                PaymentAllocation(
                    payment_id=first_payment.id, student_id=student.id, amount=Decimal("40")
                ),
                PaymentAllocation(
                    payment_id=second_payment.id, student_id=student.id, amount=Decimal("100")
                ),
                StellarAnchor(
                    payment_id=first_payment.id,
                    commitment_hash="1" * 64,
                    status="pending",
                ),
                StellarAnchor(
                    payment_id=second_payment.id,
                    commitment_hash="2" * 64,
                    status="pending",
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=first.id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("100"),
                    reference="FEE-FIRST",
                    fee_assignment_id=first_assignment.id,
                    created_at=datetime(2027, 1, 10, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=first.id,
                    student_id=student.id,
                    entry_type="payment",
                    amount=Decimal("-40"),
                    reference="ACC-P-1",
                    payment_id=first_payment.id,
                    created_at=datetime(2027, 2, 2, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="fee_charge",
                    amount=Decimal("200"),
                    reference="FEE-SECOND",
                    fee_assignment_id=second_assignment.id,
                    created_at=datetime(2027, 5, 21, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="requirement_charge",
                    amount=Decimal("30"),
                    reference="REQ-TRIP",
                    requirement_assignment_id=requirement_assignment.id,
                    created_at=datetime(2027, 5, 22, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="discount",
                    amount=Decimal("-20"),
                    reference="ADJ-DISCOUNT",
                    billing_adjustment_id=adjustment.id,
                    created_at=datetime(2027, 5, 24, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="payment",
                    amount=Decimal("-100"),
                    reference="ACC-P-2",
                    payment_id=second_payment.id,
                    created_at=datetime(2027, 5, 25, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="refund",
                    amount=Decimal("10"),
                    reference="REFUND-1",
                    description="Refund returned to payer",
                    created_at=datetime(2027, 5, 26, tzinfo=UTC),
                ),
                LedgerEntry(
                    school_id=school.id,
                    period_id=second.id,
                    student_id=student.id,
                    entry_type="reversal",
                    amount=Decimal("-5"),
                    reference="REVERSAL-1",
                    description="Charge correction reversal",
                    created_at=datetime(2027, 5, 27, tzinfo=UTC),
                ),
                SchoolMembership(school_id=school.id, auth_user_id=user_id, role="owner"),
            ]
        )
        session.commit()
        ids = {
            "school": school.id,
            "other_student": other_student.id,
            "student": student.id,
            "period": second.id,
            "payment": second_payment.id,
        }

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email="owner@example.com"
    )
    try:
        yield engine, user_id, ids, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_statement_recalculates_running_balance_and_preserves_context(account_workspace) -> None:
    _engine, _user_id, ids, client = account_workspace
    response = client.get(f"/api/v1/students/{ids['student']}/statement?period_id={ids['period']}")
    assert response.status_code == 200, response.text
    statement = response.json()
    assert statement["summary"] == {
        "opening_balance": "60.00",
        "charges": "230.00",
        "credits": "20.00",
        "payments": "100.00",
        "refunds": "10.00",
        "reversals": "-5.00",
        "period_activity": "115.00",
        "closing_balance": "175.00",
        "physical_requirements": 1,
    }
    financial_lines = [item for item in statement["lines"] if item["is_financial"]]
    assert [item["balance"] for item in financial_lines] == [
        "60.00",
        "260.00",
        "290.00",
        "270.00",
        "170.00",
        "180.00",
        "175.00",
    ]
    assert sum(Decimal(item["amount"]) for item in financial_lines[1:]) == Decimal("115")
    assert statement["placement"]["class_name"] == "Primary Seven"
    assert statement["guardian"]["name"] == "Sarah Kato"
    assert "Private" not in str(statement)
    fee_line = next(item for item in statement["lines"] if item["entry_type"] == "fee_charge")
    assert fee_line["category"] == "optional_purchase"
    assert {item["name"] for item in fee_line["components"]} == {
        "Tuition",
        "Candidate uniform",
    }
    physical = next(
        item for item in statement["lines"] if item["entry_type"] == "physical_requirement"
    )
    assert physical["amount"] == "0.00" and physical["balance"] == "290.00"
    query = f"school_id={ids['school']}&period_id={ids['period']}"
    report = client.get(
        f"/api/v1/reports/collections?{query}&start_date=2027-05-01&end_date=2027-08-31"
    ).json()
    dashboard = client.get(f"/api/v1/dashboard?{query}").json()["metrics"]
    assert report["billed"] == dashboard["billed"] == 215.0
    assert report["collected"] == dashboard["collected"] == 100.0
    assert report["period_activity"] == Decimal(statement["summary"]["period_activity"])
    assert report["outstanding"] == Decimal(statement["summary"]["closing_balance"])
    assert dashboard["outstanding"] == report["outstanding"]
    assert dashboard["accountsInArrears"] == 1
    receipt_response = client.get(f"/api/v1/payments/{ids['payment']}/receipt")
    assert receipt_response.status_code == 200, receipt_response.text
    receipt = receipt_response.json()
    assert Decimal(receipt["billed"]) == Decimal(str(report["billed"]))
    assert Decimal(receipt["paid_to_date"]) == Decimal(str(report["collected"]))
    assert Decimal(receipt["balance"]) == Decimal(statement["summary"]["closing_balance"])
    arrears = client.get(f"/api/v1/arrears?{query}&as_of=2027-07-01").json()
    assert arrears["items"][0]["balance"] == statement["summary"]["closing_balance"]


def test_statement_csv_authorization_and_tenant_isolation(account_workspace) -> None:
    engine, user_id, ids, client = account_workspace
    csv_response = client.get(
        f"/api/v1/students/{ids['student']}/statement.csv?period_id={ids['period']}"
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Closing balance,175.00" in csv_response.text
    denied = client.get(
        f"/api/v1/students/{ids['other_student']}/statement?period_id={ids['period']}"
    )
    assert denied.status_code == 404
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "auditor"
        session.commit()
    auditor = client.get(f"/api/v1/students/{ids['student']}/statement?period_id={ids['period']}")
    assert auditor.status_code == 200


def test_report_centre_uses_canonical_totals_and_server_csv(account_workspace) -> None:
    engine, user_id, ids, client = account_workspace
    parameters = {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "start_date": "2027-05-01",
        "end_date": "2027-08-31",
    }
    catalog = client.get("/api/v1/reports/centre", params={"school_id": ids["school"]})
    assert catalog.status_code == 200, catalog.text
    assert {item["key"] for item in catalog.json()["reports"]} >= {
        "collections_daily",
        "learner_balances",
        "arrears_aging",
        "requirements",
        "cash_up",
        "billing_vs_collection",
    }
    balances = client.get("/api/v1/reports/centre/learner_balances", params=parameters)
    assert balances.status_code == 200, balances.text
    payload = balances.json()
    assert payload["row_count"] == 1
    assert payload["rows"][0]["closing"] == 175.0
    assert {item["label"]: item["value"] for item in payload["metrics"]} == {
        "Opening balance": 60.0,
        "Net assessed": 215.0,
        "Net collected": 100.0,
        "Closing balance": 175.0,
    }
    csv_response = client.get(
        "/api/v1/reports/centre/learner_balances/export.csv", params=parameters
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert (
        "Admission,Learner,Class,Stream,Opening,Net assessed,Net collected,Closing"
        in csv_response.text
    )
    assert (
        "ACC-001,Amina Kato,Primary Seven,No stream,60.00,215.00,100.00,175.00" in csv_response.text
    )
    for report_type in (item["key"] for item in catalog.json()["reports"]):
        response = client.get(f"/api/v1/reports/centre/{report_type}", params=parameters)
        assert response.status_code == 200, f"{report_type}: {response.text}"
        assert response.json()["report_type"] == report_type
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        membership.role = "cashier"
        session.commit()
    denied = client.get("/api/v1/reports/centre/learner_balances", params=parameters)
    assert denied.status_code == 403
