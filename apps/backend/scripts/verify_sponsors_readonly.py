from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get(f"/api/v1/sponsor-programmes?school_id={school['id']}")
    response.raise_for_status()
    programmes = response.json()
    assert all(float(item["allocated"]) <= float(item["budget"]) for item in programmes)
    print(f"Sponsor programmes ready: {len(programmes)} programme(s)")


if __name__ == "__main__":
    main()
