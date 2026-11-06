import hashlib
import hmac
import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api import integrations
from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    Enrollment,
    IntegrationExchangeLog,
    IntegrationImportBatch,
    LearnerIdentity,
    Person,
    School,
    SchoolMembership,
    SchoolOrganization,
    Student,
)


@pytest.fixture
def integration_workspace(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    owner_id = uuid.uuid4()
    with Session(engine) as session:
        organization = SchoolOrganization(name="Interoperable School", emis_code="EMIS-100")
        school = School(
            organization=organization,
            name="Interoperable School",
            unit_name="Primary section",
            unit_type="primary",
        )
        other = School(
            organization=organization,
            name="Interoperable School",
            unit_name="Secondary section",
            unit_type="secondary",
        )
        session.add_all([school, other])
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
            opening_date=date(2027, 1, 1),
            due_date=date(2027, 2, 1),
            closing_date=date(2027, 4, 30),
            status="open",
        )
        academic_class = AcademicClass(
            school_id=school.id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        identity = LearnerIdentity(organization_id=organization.id)
        person = Person(first_name="Amina", last_name="Nabirye", date_of_birth=date(2013, 5, 2))
        session.add_all([period, academic_class, identity, person])
        session.flush()
        student = Student(
            school_id=school.id,
            learner_identity_id=identity.id,
            person_id=person.id,
            admission_no="PRI-001",
            learner_identification_number="LIN-001",
            gender="female",
        )
        session.add(student)
        session.flush()
        session.add_all(
            [
                Enrollment(
                    student_id=student.id,
                    class_id=academic_class.id,
                    period_id=period.id,
                    academic_year=2027,
                    term=1,
                ),
                SchoolMembership(
                    school_id=school.id,
                    auth_user_id=owner_id,
                    member_email="owner@example.com",
                    role="owner",
                ),
            ]
        )
        session.commit()
        ids = {
            "organization": organization.id,
            "school": school.id,
            "other": other.id,
            "identity": identity.id,
            "student": student.id,
        }

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=owner_id, email="owner@example.com"
    )
    monkeypatch.setattr(integrations, "_safe_webhook_url", lambda _url: None)
    try:
        yield engine, ids, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_client(client: TestClient, school_id: uuid.UUID, **overrides):
    payload = {
        "name": "Student information system",
        "purpose": "Keep approved learner placement records synchronized",
        "lawful_basis": "School administration agreement",
        "scopes": ["learners:read", "imports:write"],
        "allowed_fields": ["identity", "demographics", "placement"],
        "rate_limit_per_minute": 60,
    }
    payload.update(overrides)
    return client.post(
        "/api/v1/integrations/clients",
        headers={"X-School-ID": str(school_id)},
        json=payload,
    )


def test_scoped_export_is_canonical_minimized_and_audited(integration_workspace) -> None:
    engine, ids, client = integration_workspace
    created = create_client(client, ids["school"])
    assert created.status_code == 201, created.text
    api_key = created.json()["api_key"]
    exported = client.get(
        "/api/integration/v1/learners",
        headers={"Authorization": f"Bearer {api_key}", "X-Correlation-ID": "SYNC-001"},
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["schema_version"] == "harambeeone.v1"
    assert body["organization"]["id"] == str(ids["organization"])
    assert body["unit"]["id"] == str(ids["school"])
    assert body["records"][0]["stable_learner_id"] == str(ids["identity"])
    assert body["records"][0]["placement"]["canonical_class_code"] == "P7"
    assert "guardian" not in body["records"][0]
    with Session(engine) as session:
        log = session.scalar(select(IntegrationExchangeLog))
        assert log.correlation_id == "SYNC-001"
        assert log.resource_type == "learners"
        assert json.loads(log.fields_json) == ["demographics", "identity", "placement"]


def test_rotation_and_revocation_immediately_invalidate_credentials(integration_workspace) -> None:
    _engine, ids, client = integration_workspace
    created = create_client(client, ids["school"])
    client_id = created.json()["id"]
    old_key = created.json()["api_key"]
    rotated = client.post(
        f"/api/v1/integrations/clients/{client_id}/rotate",
        headers={"X-School-ID": str(ids["school"])},
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert (
        client.get(
            "/api/integration/v1/learners", headers={"Authorization": f"Bearer {old_key}"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/integration/v1/learners", headers={"Authorization": f"Bearer {new_key}"}
        ).status_code
        == 200
    )
    revoked = client.delete(
        f"/api/v1/integrations/clients/{client_id}",
        headers={"X-School-ID": str(ids["school"])},
    )
    assert revoked.status_code == 204
    assert (
        client.get(
            "/api/integration/v1/learners", headers={"Authorization": f"Bearer {new_key}"}
        ).status_code
        == 401
    )


def test_scope_and_rate_limit_are_enforced(integration_workspace) -> None:
    _engine, ids, client = integration_workspace
    created = create_client(
        client,
        ids["school"],
        scopes=["learners:read"],
        rate_limit_per_minute=10,
    )
    api_key = created.json()["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    assert client.get("/api/integration/v1/transfers", headers=headers).status_code == 403
    for _ in range(9):
        assert client.get("/api/integration/v1/learners", headers=headers).status_code == 200
    assert client.get("/api/integration/v1/learners", headers=headers).status_code == 429


def test_import_conflicts_are_quarantined_and_retries_are_idempotent(
    integration_workspace,
) -> None:
    engine, ids, client = integration_workspace
    api_key = create_client(client, ids["school"]).json()["api_key"]
    payload = {
        "schema_version": "harambeeone.v1",
        "resource_type": "learners",
        "idempotency_key": "IMPORT-2027-001",
        "records": [
            {
                "stable_learner_id": str(ids["identity"]),
                "organization_id": str(ids["organization"]),
                "source_unit_id": str(ids["school"]),
                "local_student_id": str(ids["student"]),
                "admission_no": "CHANGED-ADMISSION",
                "status": "active",
                "first_name": "Amina",
                "last_name": "Nabirye",
                "canonical_class_code": "P7",
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    imported = client.post("/api/integration/v1/imports", headers=headers, json=payload)
    assert imported.status_code == 202, imported.text
    assert imported.json()["status"] == "quarantined"
    assert imported.json()["issues"][0]["fields"] == ["admission_no"]
    replay = client.post("/api/integration/v1/imports", headers=headers, json=payload)
    assert replay.status_code == 202
    assert replay.json()["idempotent_replay"] is True
    changed = {**payload, "records": [{**payload["records"][0], "status": "completed"}]}
    assert (
        client.post("/api/integration/v1/imports", headers=headers, json=changed).status_code == 409
    )
    with Session(engine) as session:
        assert session.get(Student, ids["student"]).admission_no == "PRI-001"
        assert session.scalar(select(func.count(IntegrationImportBatch.id))) == 1


def test_webhook_is_signed_and_failed_delivery_can_retry(
    integration_workspace, monkeypatch
) -> None:
    _engine, ids, client = integration_workspace
    integration_client = create_client(client, ids["school"]).json()
    webhook = client.post(
        "/api/v1/integrations/webhooks",
        headers={"X-School-ID": str(ids["school"])},
        json={
            "integration_client_id": integration_client["id"],
            "url": "https://hooks.example.com/harambee",
            "event_types": ["integration.test", "learner.transfer.accepted"],
        },
    )
    assert webhook.status_code == 201, webhook.text
    calls = []

    def fail_once(url, body, headers):
        calls.append((url, body, headers))
        return 503, "try later"

    monkeypatch.setattr(integrations, "_post_webhook", fail_once)
    tested = client.post(
        f"/api/v1/integrations/webhooks/{webhook.json()['id']}/test",
        headers={"X-School-ID": str(ids["school"])},
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "failed"
    _, body, headers = calls[0]
    timestamp = headers["X-Harambee-Timestamp"]
    expected = hmac.new(
        webhook.json()["signing_secret"].encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Harambee-Signature"] == f"v1={expected}"

    monkeypatch.setattr(integrations, "_post_webhook", lambda _url, _body, _headers: (204, ""))
    retried = client.post(
        f"/api/v1/integrations/deliveries/{tested.json()['id']}/retry",
        headers={"X-School-ID": str(ids["school"])},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "delivered"
    assert retried.json()["attempt_count"] == 2
