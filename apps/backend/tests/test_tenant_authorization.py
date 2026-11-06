import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicPeriod,
    AcademicYear,
    AuditEvent,
    Person,
    School,
    SchoolMembership,
    SchoolOrganization,
    Student,
)


@pytest.fixture
def authorization_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    with Session(engine) as session:
        own_organization = SchoolOrganization(name="Own School")
        other_organization = SchoolOrganization(name="Other School")
        own_school = School(
            organization=own_organization,
            name="Own School",
            unit_name="Main section",
            unit_type="custom",
        )
        other_school = School(
            organization=other_organization,
            name="Other School",
            unit_name="Main section",
            unit_type="custom",
        )
        session.add_all([own_school, other_school])
        session.flush()
        own_year = AcademicYear(
            school_id=own_school.id,
            name="2026 Academic Year",
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="open",
        )
        other_year = AcademicYear(
            school_id=other_school.id,
            name="2026 Academic Year",
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="open",
        )
        session.add_all([own_year, other_year])
        session.flush()
        session.add_all(
            [
                AcademicPeriod(
                    academic_year_id=own_year.id,
                    school_id=own_school.id,
                    name="Term 1",
                    sequence=1,
                    opening_date=date(2026, 1, 1),
                    due_date=date(2026, 2, 1),
                    closing_date=date(2026, 4, 30),
                    status="open",
                ),
                AcademicPeriod(
                    academic_year_id=other_year.id,
                    school_id=other_school.id,
                    name="Term 1",
                    sequence=1,
                    opening_date=date(2026, 1, 1),
                    due_date=date(2026, 2, 1),
                    closing_date=date(2026, 4, 30),
                    status="open",
                ),
            ]
        )
        session.add_all(
            [
                SchoolMembership(
                    school_id=own_school.id,
                    auth_user_id=user_id,
                    role="owner",
                ),
                SchoolMembership(
                    school_id=other_school.id,
                    auth_user_id=other_user_id,
                    role="owner",
                ),
            ]
        )
        person = Person(first_name="Other", last_name="Learner")
        session.add(person)
        session.flush()
        other_student = Student(
            school_id=other_school.id,
            person_id=person.id,
            admission_no="OTHER-001",
            gender="female",
        )
        session.add(other_student)
        session.commit()
        own_school_id = own_school.id
        other_school_id = other_school.id
        other_student_id = other_student.id

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    def user_override():
        return AuthenticatedUser(id=user_id, email="owner@example.com")

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = user_override
    try:
        yield engine, user_id, own_school_id, other_school_id, other_student_id
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_operational_api_requires_authentication() -> None:
    response = TestClient(app).get("/api/v1/schools")

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_school_listing_only_returns_membership_school(authorization_workspace) -> None:
    _engine, _user_id, own_school_id, _other_school_id, _student_id = authorization_workspace

    response = TestClient(app).get("/api/v1/schools")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(own_school_id)]


def test_current_context_exposes_server_derived_role_and_permissions(
    authorization_workspace,
) -> None:
    _engine, _user_id, own_school_id, _other_school_id, _student_id = authorization_workspace

    response = TestClient(app).get("/api/v1/me/context")

    assert response.status_code == 200
    assert response.json()["id"] == str(own_school_id)
    assert response.json()["role"] == "owner"
    assert "school:manage" in response.json()["permissions"]


def test_user_can_select_between_explicit_school_memberships(authorization_workspace) -> None:
    engine, user_id, _own_school_id, other_school_id, _student_id = authorization_workspace
    with Session(engine) as session:
        session.add(
            SchoolMembership(
                school_id=other_school_id,
                auth_user_id=user_id,
                role="auditor",
            )
        )
        session.commit()

    selected = TestClient(app).get(
        "/api/v1/me/context", headers={"X-School-ID": str(other_school_id)}
    )

    assert selected.status_code == 200
    assert selected.json()["id"] == str(other_school_id)
    assert selected.json()["role"] == "auditor"


def test_unassigned_school_section_cannot_be_selected(authorization_workspace) -> None:
    _engine, _user_id, _own_school_id, other_school_id, _student_id = authorization_workspace

    response = TestClient(app).get(
        "/api/v1/me/context", headers={"X-School-ID": str(other_school_id)}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to the selected school section"


def test_owner_can_add_a_separate_section_to_the_same_institution(
    authorization_workspace,
) -> None:
    engine, user_id, own_school_id, _other_school_id, _student_id = authorization_workspace
    with Session(engine) as session:
        organization_id = session.get(School, own_school_id).organization_id

    response = TestClient(app).post(
        "/api/v1/schools",
        headers={"X-School-ID": str(own_school_id)},
        json={
            "name": "Own School",
            "programme_codes": ["primary"],
            "canonical_codes": ["P1", "P2"],
            "default_streams": [],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == str(organization_id)
    assert response.json()["unit_type"] == "primary"
    with Session(engine) as session:
        memberships = session.scalars(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        ).all()
        assert len(memberships) == 2


def test_cross_school_query_is_forbidden(authorization_workspace) -> None:
    _engine, _user_id, _own_school_id, other_school_id, _student_id = authorization_workspace

    response = TestClient(app).get(f"/api/v1/schools/{other_school_id}/classes")

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this institution"


def test_cross_school_resource_id_is_not_disclosed(authorization_workspace) -> None:
    _engine, _user_id, _own_school_id, _other_school_id, student_id = authorization_workspace

    response = TestClient(app).get(f"/api/v1/students/{student_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Learner not found"


def test_auditor_can_read_but_cannot_write(authorization_workspace) -> None:
    engine, user_id, own_school_id, _other_school_id, _student_id = authorization_workspace
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        assert membership is not None
        membership.role = "auditor"
        session.commit()

    client = TestClient(app)
    read_response = client.get(f"/api/v1/payments?school_id={own_school_id}")
    write_response = client.post(
        "/api/v1/fee-categories",
        json={
            "school_id": str(own_school_id),
            "name": "Tuition",
            "code": "TUIT",
            "category_type": "tuition",
            "priority": 1,
        },
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403
    assert write_response.json()["detail"] == "Your institution role does not permit this action"


def test_bursar_can_manage_classes(authorization_workspace) -> None:
    engine, user_id, own_school_id, _other_school_id, _student_id = authorization_workspace
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        assert membership is not None
        membership.role = "bursar"
        session.commit()

    response = TestClient(app).post(
        f"/api/v1/schools/{own_school_id}/classes",
        json={
            "name": "Primary One",
            "level": "primary",
            "canonical_code": "P1",
            "sort_order": 1,
            "streams": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Primary One"


def test_cashier_can_record_payment_but_cannot_configure_fees(
    authorization_workspace,
) -> None:
    engine, user_id, own_school_id, _other_school_id, _student_id = authorization_workspace
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        assert membership is not None
        membership.role = "cashier"
        person = Person(first_name="Cash", last_name="Learner")
        session.add(person)
        session.flush()
        student = Student(
            school_id=own_school_id,
            person_id=person.id,
            admission_no="OWN-001",
            gender="male",
        )
        session.add(student)
        session.commit()
        student_id = student.id

    client = TestClient(app)
    payment_response = client.post(
        "/api/v1/payments",
        json={
            "school_id": str(own_school_id),
            "student_id": str(student_id),
            "external_reference": "CASH-TEST-001",
            "payer_name": "Test Guardian",
            "channel": "cash",
            "amount": 50000,
        },
    )
    fee_response = client.post(
        "/api/v1/fee-categories",
        json={
            "school_id": str(own_school_id),
            "name": "Tuition",
            "code": "TUIT",
            "category_type": "tuition",
            "priority": 1,
        },
    )

    assert payment_response.status_code == 201
    assert payment_response.json()["external_reference"] == "CASH-TEST-001"
    assert fee_response.status_code == 403
    with Session(engine) as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.entity_type == "payment"))
        assert event is not None
        assert event.actor == "owner@example.com"


def test_cross_school_write_payload_is_forbidden(authorization_workspace) -> None:
    _engine, _user_id, _own_school_id, other_school_id, _student_id = authorization_workspace

    response = TestClient(app).post(
        "/api/v1/fee-categories",
        json={
            "school_id": str(other_school_id),
            "name": "Foreign fee",
            "code": "FOREIGN",
            "category_type": "other",
            "priority": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this institution"


def test_authenticated_user_without_membership_is_forbidden(authorization_workspace) -> None:
    _engine, _user_id, _own_school_id, _other_school_id, _student_id = authorization_workspace
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid.uuid4(), email="new@example.com"
    )

    response = TestClient(app).get("/api/v1/schools")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Complete institution setup before using the bursar workspace"
    )
