from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    learner = client.get("/api/v1/students", params={"school_id": school["id"]}).json()["items"][0]
    profile = client.get(f"/api/v1/students/{learner['id']}").json()
    guardian = next(item for item in profile["guardians"] if item["is_primary"])
    response = client.put(
        f"/api/v1/students/{learner['id']}/profile",
        json={
            "first_name": profile["first_name"],
            "middle_name": profile["middle_name"],
            "last_name": profile["last_name"],
            "date_of_birth": profile["date_of_birth"],
            "gender": profile["gender"],
            "learner_identification_number": profile["learner_identification_number"],
            "boarding_status": profile["boarding_status"],
            "nationality": profile["nationality"],
            "previous_school": profile["previous_school"],
            "special_needs": profile["special_needs"],
            "guardian_id": guardian["id"],
            "guardian_first_name": guardian["first_name"],
            "guardian_last_name": guardian["last_name"],
            "guardian_relationship": guardian["relationship"],
            "guardian_phone": guardian["phone"],
            "guardian_email": guardian["email"],
        },
    )
    response.raise_for_status()
    assert response.json()["updated"] is True
    print("Student editing ready: learner identity and primary guardian saved atomically")


if __name__ == "__main__":
    main()
