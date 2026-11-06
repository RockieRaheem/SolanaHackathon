from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get("/api/v1/dashboard", params={"school_id": school["id"]})
    response.raise_for_status()
    dashboard = response.json()
    if dashboard["mode"] != "LIVE":
        raise RuntimeError("Dashboard is not using the live ledger")
    print(
        f"Dashboard ready: {dashboard['metrics']['activeLearners']} learners, "
        f"UGX {dashboard['metrics']['collected']:,.0f} collected"
    )


if __name__ == "__main__":
    main()
