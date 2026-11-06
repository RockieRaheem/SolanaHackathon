from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get(f"/api/v1/reconciliation/transactions?school_id={school['id']}")
    response.raise_for_status()
    rows = response.json()
    assert all(row["status"] in {"unmatched", "suggested", "reconciled"} for row in rows)
    print(f"Reconciliation register ready: {len(rows)} source transaction(s)")


if __name__ == "__main__":
    main()
