from verification_client import authenticated_client


def main() -> None:
    client = authenticated_client()
    school = client.get("/api/v1/schools").json()[0]
    payments = client.get(f"/api/v1/payments?school_id={school['id']}").json()
    if not payments:
        print("Receipt API ready; no existing payment is available for a read-only detail check")
        return
    payment = payments[0]
    receipt = client.get(f"/api/v1/payments/{payment['id']}/receipt")
    receipt.raise_for_status()
    body = receipt.json()
    assert body["receipt_no"] == payment["receipt_no"]
    assert body["commitment_hash"] == payment["commitment_hash"]
    assert float(body["amount"]) > 0
    print(f"Official receipt readable: {body['receipt_no']}")


if __name__ == "__main__":
    main()
