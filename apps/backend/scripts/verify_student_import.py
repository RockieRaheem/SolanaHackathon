from uuid import uuid4

from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    classes = client.get(f"/api/v1/schools/{school['id']}/classes").json()
    group = classes[0]
    before = client.get("/api/v1/students", params={"school_id": school["id"]}).json()["total"]
    response = client.post(
        "/api/v1/student-imports",
        json={
            "validate_only": True,
            "students": [
                {
                    "school_id": school["id"],
                    "first_name": "Import",
                    "last_name": "Verification",
                    "gender": "female",
                    "learner_identification_number": f"TEST-{str(uuid4())[:16]}",
                    "class_id": group["id"],
                    "stream_id": None,
                    "academic_year": 2026,
                    "term": 1,
                    "guardians": [
                        {
                            "first_name": "Test",
                            "last_name": "Guardian",
                            "relationship": "guardian",
                            "phone": "+256700000001",
                            "is_primary": True,
                        }
                    ],
                }
            ],
        },
    )
    if not response.is_success:
        raise RuntimeError(response.text)
    after = client.get("/api/v1/students", params={"school_id": school["id"]}).json()["total"]
    assert response.json()["valid"] == 1 and before == after
    print("Student import ready: full validation completed with no dry-run persistence")


if __name__ == "__main__":
    main()
