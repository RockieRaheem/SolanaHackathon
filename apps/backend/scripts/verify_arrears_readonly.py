from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get(f"/api/v1/arrears?school_id={school['id']}")
    response.raise_for_status()
    register = response.json()
    assert register["total_accounts"] == len(register["items"])
    assert float(register["total_overdue"]) == sum(
        float(item["overdue_amount"]) for item in register["items"]
    )
    assert all(item["days_overdue"] >= 0 for item in register["items"])
    print(f"Arrears register ready: {register['total_accounts']} overdue account(s)")


if __name__ == "__main__":
    main()
