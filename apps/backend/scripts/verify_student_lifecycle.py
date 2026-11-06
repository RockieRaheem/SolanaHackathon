from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    classes = client.get(f"/api/v1/schools/{school['id']}/classes").json()
    students = client.get("/api/v1/students", params={"school_id": school["id"]}).json()
    student_id = students["items"][0]["id"]
    profile = client.get(f"/api/v1/students/{student_id}").json()
    original_status = profile["status"]
    group = next(item for item in classes if item["name"] == profile["placement"]["class_name"])
    stream = next(
        (item for item in group["streams"] if item["name"] == profile["placement"]["stream_name"]),
        None,
    )
    try:
        changed = client.patch(f"/api/v1/students/{student_id}/status", json={"status": "archived"})
        changed.raise_for_status()
        moved = client.post(
            f"/api/v1/students/{student_id}/transfer",
            json={
                "class_id": group["id"],
                "stream_id": stream["id"] if stream else None,
                "academic_year": profile["placement"]["academic_year"],
                "term": profile["placement"]["term"],
            },
        )
        moved.raise_for_status()
        print("Learner lifecycle ready: status and period-aware placement")
    finally:
        restored = client.patch(
            f"/api/v1/students/{student_id}/status", json={"status": original_status}
        )
        restored.raise_for_status()


if __name__ == "__main__":
    main()
