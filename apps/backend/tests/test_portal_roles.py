import hashlib
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
from harambeeone_api.models import (
    DonorProfile,
    GuardianAccountLink,
    GuardianInvitation,
    GuardianLink,
    Person,
    School,
    SchoolMembership,
    Student,
    SupportNotification,
    SupportNotificationOutbox,
)


@pytest.fixture
def portal_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    staff_id = uuid.uuid4()
    guardian_user_id = uuid.uuid4()
    current_user = {
        "value": AuthenticatedUser(id=staff_id, email="bursar@school.test")
    }
    with Session(engine) as session:
        school = School(name="Portal School")
        other_school = School(name="Other School")
        session.add_all([school, other_school])
        session.flush()
        session.add(SchoolMembership(school_id=school.id, auth_user_id=staff_id, role="owner"))
        learner_person = Person(first_name="Private", last_name="Learner")
        guardian_person = Person(
            first_name="Grace",
            last_name="Guardian",
            email="guardian@example.com",
            phone="+256700000001",
        )
        other_learner_person = Person(first_name="Other", last_name="Learner")
        other_guardian_person = Person(
            first_name="Other",
            last_name="Guardian",
            email="other@example.com",
            phone="+256700000002",
        )
        session.add_all(
            [learner_person, guardian_person, other_learner_person, other_guardian_person]
        )
        session.flush()
        learner = Student(
            school_id=school.id,
            person_id=learner_person.id,
            admission_no="PS-001",
            gender="female",
        )
        other_learner = Student(
            school_id=other_school.id,
            person_id=other_learner_person.id,
            admission_no="OS-001",
            gender="male",
        )
        session.add_all([learner, other_learner])
        session.flush()
        guardian = GuardianLink(
            student_id=learner.id,
            person_id=guardian_person.id,
            relationship="mother",
            is_primary=True,
        )
        other_guardian = GuardianLink(
            student_id=other_learner.id,
            person_id=other_guardian_person.id,
            relationship="father",
            is_primary=True,
        )
        session.add_all([guardian, other_guardian])
        session.commit()
        values = {
            "school_id": school.id,
            "guardian_id": guardian.id,
            "other_guardian_id": other_guardian.id,
            "learner_id": learner.id,
            "staff_id": staff_id,
            "guardian_user_id": guardian_user_id,
        }

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    def user_override():
        return current_user["value"]

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = user_override
    try:
        yield engine, current_user, values
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _invite(client: TestClient, values: dict) -> dict:
    response = client.post(
        "/api/v1/support/guardian-invitations",
        json={
            "school_id": str(values["school_id"]),
            "guardian_link_id": str(values["guardian_id"]),
        },
    )
    assert response.status_code == 201
    return response.json()


def test_guardian_invitation_is_hashed_scoped_and_single_use(portal_workspace) -> None:
    engine, current_user, values = portal_workspace
    client = TestClient(app)
    invitation = _invite(client, values)
    token = invitation["claim_token"]
    with Session(engine) as session:
        stored = session.scalar(select(GuardianInvitation))
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in stored.token_hash
        notification = session.scalar(select(SupportNotification))
        outbox = session.scalar(select(SupportNotificationOutbox))
        assert notification is not None and outbox is not None
        assert token not in notification.href
        assert token not in outbox.payload_json

    current_user["value"] = AuthenticatedUser(
        id=values["guardian_user_id"], email="wrong@example.com"
    )
    wrong_account = client.post(
        "/api/v1/guardian/invitations/accept", json={"token": token}
    )
    assert wrong_account.status_code == 403

    current_user["value"] = AuthenticatedUser(
        id=values["guardian_user_id"], email="guardian@example.com"
    )
    accepted = client.post("/api/v1/guardian/invitations/accept", json={"token": token})
    replay = client.post("/api/v1/guardian/invitations/accept", json={"token": token})
    learners = client.get("/api/v1/guardian/learners")

    assert accepted.status_code == 200
    assert accepted.json()["href"] == "/guardian"
    assert replay.status_code == 409
    assert learners.status_code == 200
    assert learners.json() == [
        {
            "student_id": str(values["learner_id"]),
            "school_id": str(values["school_id"]),
            "school_name": "Portal School",
            "learner_name": "Private Learner",
            "admission_no": "PS-001",
            "relationship": "mother",
            "is_primary": True,
            "verified_at": learners.json()[0]["verified_at"],
        }
    ]
    with Session(engine) as session:
        link = session.scalar(select(GuardianAccountLink))
        assert link is not None
        assert link.auth_user_id == values["guardian_user_id"]


def test_invitation_rejects_cross_school_guardian(portal_workspace) -> None:
    _engine, _current_user, values = portal_workspace
    response = TestClient(app).post(
        "/api/v1/support/guardian-invitations",
        json={
            "school_id": str(values["school_id"]),
            "guardian_link_id": str(values["other_guardian_id"]),
        },
    )

    assert response.status_code == 404


def test_expired_invitation_cannot_be_accepted(portal_workspace) -> None:
    engine, current_user, values = portal_workspace
    client = TestClient(app)
    invitation = _invite(client, values)
    with Session(engine) as session:
        stored = session.scalar(select(GuardianInvitation))
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
    current_user["value"] = AuthenticatedUser(
        id=values["guardian_user_id"], email="guardian@example.com"
    )

    response = client.post(
        "/api/v1/guardian/invitations/accept",
        json={"token": invitation["claim_token"]},
    )

    assert response.status_code == 410


def test_donor_activation_does_not_grant_school_or_guardian_access(portal_workspace) -> None:
    engine, current_user, _values = portal_workspace
    donor_user_id = uuid.uuid4()
    current_user["value"] = AuthenticatedUser(
        id=donor_user_id, email="donor@example.com"
    )
    client = TestClient(app)

    before = client.get("/api/v1/me/portals")
    activated = client.post(
        "/api/v1/me/donor-profile",
        json={"display_name": "Community Donor", "show_public_name": False},
    )
    after = client.get("/api/v1/me/portals")
    guardian_learners = client.get("/api/v1/guardian/learners")
    school = client.get("/api/v1/schools")

    assert before.status_code == 200
    assert before.json()["portals"] == []
    assert activated.status_code == 201
    assert [item["type"] for item in after.json()["portals"]] == ["donor"]
    assert guardian_learners.status_code == 200
    assert guardian_learners.json() == []
    assert school.status_code == 403
    with Session(engine) as session:
        assert session.get(DonorProfile, donor_user_id) is not None


def test_portal_preference_requires_an_available_role(portal_workspace) -> None:
    _engine, current_user, _values = portal_workspace
    current_user["value"] = AuthenticatedUser(id=uuid.uuid4(), email="plain@example.com")

    response = TestClient(app).patch(
        "/api/v1/me/portal-preference", json={"preferred_workspace": "guardian"}
    )

    assert response.status_code == 403
