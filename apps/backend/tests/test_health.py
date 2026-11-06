import uuid

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import get_session
from harambeeone_api.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "harambeeone-api"


def test_database_errors_return_safe_service_response() -> None:
    def unavailable_session():
        raise SQLAlchemyError("private connection detail")
        yield

    app.dependency_overrides[get_session] = unavailable_session
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid.uuid4(), email="bursar@example.com"
    )
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/api/v1/schools")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The finance database is temporarily unavailable",
        "code": "DATABASE_UNAVAILABLE",
    }
    assert "private connection detail" not in response.text
