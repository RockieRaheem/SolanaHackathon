import os

from fastapi.testclient import TestClient

from harambeeone_api.main import app


def authenticated_client() -> TestClient:
    token = os.environ.get("SUPABASE_TEST_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set SUPABASE_TEST_ACCESS_TOKEN to a signed-in test user's access token")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})
