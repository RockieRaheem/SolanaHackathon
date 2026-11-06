from sqlalchemy import text
from sqlalchemy.orm import Session
from verification_client import authenticated_client

from harambeeone_api.database import get_engine


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get(f"/api/v1/audit-events?school_id={school['id']}")
    response.raise_for_status()
    assert all(event["school_id"] == school["id"] for event in response.json())
    with Session(get_engine()) as session:
        trigger_count = session.scalar(
            text("select count(*) from pg_trigger where tgname like 'audit_%'")
        )
    assert trigger_count == 14
    print(f"Audit trail ready: {len(response.json())} event(s)")


if __name__ == "__main__":
    main()
