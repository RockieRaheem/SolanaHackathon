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
    AuditEvent,
    Enrollment,
    GuardianLink,
    IntegrationOutboxEvent,
    LearnerIdentity,
    LearnerTransferCase,
    LedgerEntry,
    Person,
    School,
    SchoolMembership,
    SchoolOrganization,
    Student,
)


@pytest.fixture
def transfer_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        organization = SchoolOrganization(name="Linked School")
        other_organization = SchoolOrganization(name="Foreign School")
        source = School(
            organization=organization,
            name="Linked School",
            unit_name="Primary section",
            unit_type="primary",
        )
        target = School(
            organization=organization,
            name="Linked School",
            unit_name="Secondary section",
            unit_type="secondary",
        )
        foreign = School(
            organization=other_organization,
            name="Foreign School",
            unit_name="Secondary section",
            unit_type="secondary",
        )
        session.add_all([source, target, foreign])
        session.flush()
        source_year = AcademicYear(
            school_id=source.id,
            name="2027 Academic Year",
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status="open",
        )
        target_year = AcademicYear(
            school_id=target.id,
            name="2027 Academic Year",
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status="open",
        )
        session.add_all([source_year, target_year])
        session.flush()
        source_period = AcademicPeriod(
            academic_year_id=source_year.id,
            school_id=source.id,
            name="Term 1",
            sequence=1,
            opening_date=date(2027, 1, 1),
            due_date=date(2027, 2, 1),
            closing_date=date(2027, 4, 30),
            status="open",
        )
        target_period = AcademicPeriod(
            academic_year_id=target_year.id,
            school_id=target.id,
            name="Term 1",
            sequence=1,
            opening_date=date(2027, 1, 1),
            due_date=date(2027, 2, 1),
            closing_date=date(2027, 4, 30),
            status="open",
        )
        source_class = AcademicClass(
            school_id=source.id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        target_class = AcademicClass(
            school_id=target.id,
            name="Senior One",
            level="lower_secondary",
            canonical_code="S1",
            sort_order=1,
        )
        session.add_all([source_period, target_period, source_class, target_class])
        session.flush()
        identity = LearnerIdentity(organization_id=organization.id)
        learner_person = Person(
            first_name="Amina", last_name="Nabirye", date_of_birth=date(2013, 5, 2)
        )
        guardian_person = Person(
            first_name="Grace",
            last_name="Nabirye",
            phone="+256700000001",
            email="grace@example.com",
        )
        session.add_all([identity, learner_person, guardian_person])
        session.flush()
        learner = Student(
            school_id=source.id,
            learner_identity_id=identity.id,
            person_id=learner_person.id,
            admission_no="PRI-001",
            learner_identification_number="LIN-001",
            gender="female",
        )
        session.add(learner)
        session.flush()
        guardian = GuardianLink(
            student_id=learner.id,
            person_id=guardian_person.id,
            relationship="mother",
            is_primary=True,
        )
        session.add_all(
            [
                guardian,
                Enrollment(
                    student_id=learner.id,
                    class_id=source_class.id,
                    period_id=source_period.id,
                    academic_year=2027,
                    term=1,
                ),
                LedgerEntry(
                    school_id=source.id,
                    period_id=source_period.id,
                    student_id=learner.id,
                    entry_type="charge",
                    amount=Decimal("250000"),
                    reference="SOURCE-FEE",
                ),
                SchoolMembership(school_id=source.id, auth_user_id=user_id, role="owner"),
                SchoolMembership(school_id=target.id, auth_user_id=user_id, role="owner"),
            ]
        )
        session.commit()
        ids = {
            "source": source.id,
            "target": target.id,
            "foreign": foreign.id,
            "student": learner.id,
            "guardian": guardian.id,
            "target_period": target_period.id,
            "target_class": target_class.id,
            "identity": identity.id,
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


def create_case(client: TestClient, ids: dict):
    return client.post(
        "/api/v1/learner-transfers",
        headers={"X-School-ID": str(ids["source"])},
        json={
            "student_id": str(ids["student"]),
            "target_school_id": str(ids["target"]),
            "guardian_link_id": str(ids["guardian"]),
            "purpose": "Transition from primary to secondary section",
            "consent_confirmed": True,
            "consent_method": "written",
            "consent_reference": "CONSENT-001",
            "consent_recorded_at": datetime.now(UTC).isoformat(),
        },
    )


def test_consent_transfer_acceptance_preserves_source_finance_and_is_idempotent(
    transfer_workspace,
) -> None:
    engine, ids, client = transfer_workspace
    created = create_case(client, ids)
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    accepted = client.post(
        f"/api/v1/learner-transfers/{case_id}/decision",
        headers={"X-School-ID": str(ids["target"])},
        json={
            "action": "accept",
            "admission_no": "SEC-001",
            "class_id": str(ids["target_class"]),
            "period_id": str(ids["target_period"]),
        },
    )
    assert accepted.status_code == 200, accepted.text
    target_student_id = accepted.json()["target_student_id"]
    replay = client.post(
        f"/api/v1/learner-transfers/{case_id}/decision",
        headers={"X-School-ID": str(ids["target"])},
        json={
            "action": "accept",
            "admission_no": "SEC-001",
            "class_id": str(ids["target_class"]),
            "period_id": str(ids["target_period"]),
        },
    )
    assert replay.status_code == 200
    assert replay.json()["target_student_id"] == target_student_id
    with Session(engine) as session:
        source = session.get(Student, ids["student"])
        target = session.get(Student, uuid.UUID(target_student_id))
        assert source.status == "transferred"
        assert target.school_id == ids["target"]
        assert target.learner_identity_id == ids["identity"]
        assert (
            session.scalar(
                select(func.count(LedgerEntry.id)).where(LedgerEntry.student_id == source.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(Student.id)).where(Student.learner_identity_id == ids["identity"])
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(IntegrationOutboxEvent.id)).where(
                    IntegrationOutboxEvent.aggregate_id == uuid.UUID(case_id)
                )
            )
            == 4
        )


def test_transfer_requires_consent_and_linked_target(transfer_workspace) -> None:
    _engine, ids, client = transfer_workspace
    without_consent = client.post(
        "/api/v1/learner-transfers",
        headers={"X-School-ID": str(ids["source"])},
        json={
            "student_id": str(ids["student"]),
            "target_school_id": str(ids["target"]),
            "guardian_link_id": str(ids["guardian"]),
            "purpose": "Transition to the next section",
            "consent_confirmed": False,
            "consent_method": "written",
            "consent_reference": "CONSENT-002",
            "consent_recorded_at": datetime.now(UTC).isoformat(),
        },
    )
    assert without_consent.status_code == 422
    foreign = client.post(
        "/api/v1/learner-transfers",
        headers={"X-School-ID": str(ids["source"])},
        json={
            "student_id": str(ids["student"]),
            "target_school_id": str(ids["foreign"]),
            "guardian_link_id": str(ids["guardian"]),
            "purpose": "Unauthorized cross-organization move",
            "consent_confirmed": True,
            "consent_method": "written",
            "consent_reference": "CONSENT-003",
            "consent_recorded_at": datetime.now(UTC).isoformat(),
        },
    )
    assert foreign.status_code == 422


def test_only_target_can_decide_and_rejection_requires_reason(transfer_workspace) -> None:
    _engine, ids, client = transfer_workspace
    case_id = create_case(client, ids).json()["id"]
    source_decision = client.post(
        f"/api/v1/learner-transfers/{case_id}/decision",
        headers={"X-School-ID": str(ids["source"])},
        json={"action": "reject", "reason": "Not valid"},
    )
    assert source_decision.status_code == 404
    rejected = client.post(
        f"/api/v1/learner-transfers/{case_id}/decision",
        headers={"X-School-ID": str(ids["target"])},
        json={"action": "reject", "reason": "Admission documents are incomplete"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    with Session(_engine) as session:
        assert session.get(LearnerTransferCase, uuid.UUID(case_id)).target_student_id is None
        assert (
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_id == uuid.UUID(case_id),
                    AuditEvent.action == "rejected",
                )
            )
            == 2
        )


def test_duplicate_target_admission_is_rejected_without_partial_transfer(
    transfer_workspace,
) -> None:
    engine, ids, client = transfer_workspace
    with Session(engine) as session:
        identity = LearnerIdentity(
            organization_id=session.get(School, ids["target"]).organization_id
        )
        person = Person(first_name="Existing", last_name="Learner")
        session.add_all([identity, person])
        session.flush()
        session.add(
            Student(
                school_id=ids["target"],
                learner_identity_id=identity.id,
                person_id=person.id,
                admission_no="SEC-TAKEN",
                gender="female",
            )
        )
        session.commit()
    case_id = create_case(client, ids).json()["id"]
    response = client.post(
        f"/api/v1/learner-transfers/{case_id}/decision",
        headers={"X-School-ID": str(ids["target"])},
        json={
            "action": "accept",
            "admission_no": "SEC-TAKEN",
            "class_id": str(ids["target_class"]),
            "period_id": str(ids["target_period"]),
        },
    )
    assert response.status_code == 409
    with Session(engine) as session:
        case = session.get(LearnerTransferCase, uuid.UUID(case_id))
        assert case.status == "pending"
        assert case.target_student_id is None
        assert session.get(Student, ids["student"]).status == "active"
