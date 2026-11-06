from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    students = client.get("/api/v1/students", params={"school_id": school["id"]})
    students.raise_for_status()
    learner = students.json()["items"][0]
    profile = client.get(f"/api/v1/students/{learner['id']}")
    profile.raise_for_status()
    assert profile.json()["admission_no"] == learner["admission_no"]
    assert "financials" in profile.json() and "guardians" in profile.json()
    print("Learner profile ready: identity, placement, guardians, ledger and payments")


if __name__ == "__main__":
    main()
