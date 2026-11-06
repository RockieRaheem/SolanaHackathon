import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import AuditEvent, School, SchoolMembership, StaffInvitation


@pytest.fixture
def staff_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    owner_id = uuid.uuid4()
    current = {"user": AuthenticatedUser(id=owner_id, email="owner@school.example")}
    with Session(engine) as session:
        school = School(name="Access School")
        other = School(name="Other School")
        session.add_all([school, other])
        session.flush()
        session.add(
            SchoolMembership(
                school_id=school.id,
                auth_user_id=owner_id,
                member_email="owner@school.example",
                role="owner",
            )
        )
        session.commit()
        ids = {"school": school.id, "other": other.id, "owner": owner_id}

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    try:
        yield engine, ids, current, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_staff_invitation_accept_role_change_and_revoke(staff_workspace) -> None:
    engine, ids, current, client = staff_workspace
    invited = client.post(
        "/api/v1/staff-invitations",
        json={"email": "Bursar@School.example", "role": "bursar"},
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["claim_path"].split("token=", 1)[1]

    current["user"] = AuthenticatedUser(id=uuid.uuid4(), email="wrong@school.example")
    wrong = client.post("/api/v1/staff-invitations/accept", json={"token": token})
    assert wrong.status_code == 403

    staff_user_id = uuid.uuid4()
    current["user"] = AuthenticatedUser(id=staff_user_id, email="bursar@school.example")
    accepted = client.post("/api/v1/staff-invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["school_id"] == str(ids["school"])
    replay = client.post("/api/v1/staff-invitations/accept", json={"token": token})
    assert replay.status_code == 409

    current["user"] = AuthenticatedUser(id=ids["owner"], email="owner@school.example")
    access = client.get("/api/v1/staff-access")
    staff = next(row for row in access.json()["members"] if row["user_id"] == str(staff_user_id))
    changed = client.patch(
        f"/api/v1/staff-memberships/{staff['id']}", json={"role": "auditor"}
    )
    assert changed.status_code == 200
    removed = client.delete(f"/api/v1/staff-memberships/{staff['id']}")
    assert removed.status_code == 204
    with Session(engine) as session:
        assert session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == staff_user_id)
        ) is None
        actions = set(session.scalars(select(AuditEvent.action)).all())
        assert {"created", "accepted", "role_changed", "revoked"} <= actions


def test_expired_invitation_cannot_be_accepted(staff_workspace) -> None:
    engine, _ids, current, client = staff_workspace
    invited = client.post(
        "/api/v1/staff-invitations",
        json={"email": "cashier@school.example", "role": "cashier"},
    )
    token = invited.json()["claim_path"].split("token=", 1)[1]
    with Session(engine) as session:
        row = session.scalar(select(StaffInvitation))
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
    current["user"] = AuthenticatedUser(id=uuid.uuid4(), email="cashier@school.example")

    response = client.post("/api/v1/staff-invitations/accept", json={"token": token})

    assert response.status_code == 410


def test_non_owner_cannot_manage_staff(staff_workspace) -> None:
    engine, ids, current, client = staff_workspace
    bursar_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            SchoolMembership(
                school_id=ids["school"],
                auth_user_id=bursar_id,
                member_email="bursar@school.example",
                role="bursar",
            )
        )
        session.commit()
    current["user"] = AuthenticatedUser(id=bursar_id, email="bursar@school.example")

    response = client.post(
        "/api/v1/staff-invitations",
        json={"email": "cashier@school.example", "role": "cashier"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Only the section owner can manage staff access"


def test_owner_cannot_revoke_self(staff_workspace) -> None:
    _engine, _ids, _current, client = staff_workspace
    listing = client.get("/api/v1/staff-access").json()
    owner = next(row for row in listing["members"] if row["role"] == "owner")

    response = client.delete(f"/api/v1/staff-memberships/{owner['id']}")

    assert response.status_code == 409
