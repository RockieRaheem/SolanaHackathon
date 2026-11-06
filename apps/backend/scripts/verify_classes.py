from uuid import uuid4

from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    schools = client.get("/api/v1/schools")
    schools.raise_for_status()
    school_id = schools.json()[0]["id"]
    class_id = None
    class_name = f"Verification {str(uuid4())[:8]}"
    try:
        created = client.post(
            f"/api/v1/schools/{school_id}/classes",
            json={
                "name": class_name,
                "level": "other",
                "sort_order": 100,
                "streams": ["East", "West"],
            },
        )
        created.raise_for_status()
        class_id = created.json()["id"]
        updated = client.put(
            f"/api/v1/classes/{class_id}",
            json={
                "name": class_name,
                "level": "other",
                "sort_order": 99,
                "streams": ["North", "South"],
            },
        )
        updated.raise_for_status()
        assert {stream["name"] for stream in updated.json()["streams"]} == {"North", "South"}
        listed = client.get(f"/api/v1/schools/{school_id}/classes")
        listed.raise_for_status()
        assert any(item["id"] == class_id for item in listed.json())
        print("Class workflow ready: create, edit, list and safe delete")
    finally:
        if class_id:
            deleted = client.delete(f"/api/v1/classes/{class_id}")
            deleted.raise_for_status()


if __name__ == "__main__":
    main()
