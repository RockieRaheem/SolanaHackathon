from datetime import date

from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    response = client.get(
        f"/api/v1/reports/collections?school_id={school['id']}&start_date=2020-01-01&end_date={date.today()}"
    )
    response.raise_for_status()
    report = response.json()
    assert float(report["collected"]) == sum(float(row["amount"]) for row in report["transactions"])
    assert report["transaction_count"] == len(report["transactions"])
    print(f"Collections report ready: {report['transaction_count']} transaction(s)")


if __name__ == "__main__":
    main()
