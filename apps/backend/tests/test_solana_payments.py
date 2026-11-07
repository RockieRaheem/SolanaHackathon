from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from harambeeone_api import solana_payments

SIGNATURE = "3" * 88
SENDER = "7" * 44
RECIPIENT = "8" * 44
MEMO = "HARAMBEEONE:HSP-TEST123"


def rpc_result(
    *,
    sender: str = SENDER,
    recipient: str = RECIPIENT,
    lamports: int = 125,
    memo: str = MEMO,
    signer: bool = True,
):
    transaction = {
        "slot": 456,
        "blockTime": int(datetime.now(UTC).timestamp()),
        "meta": {"err": None},
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": sender, "signer": signer}],
                "instructions": [
                    {
                        "program": "system",
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": sender,
                                "destination": recipient,
                                "lamports": lamports,
                            },
                        },
                    },
                    {
                        "program": "spl-memo",
                        "programId": "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
                        "parsed": memo,
                    },
                ],
            }
        },
    }
    return transaction


def install_rpc(monkeypatch, transaction, confirmation_status: str = "confirmed"):
    def fake_rpc(method: str, _params: list):
        if method == "getSignatureStatuses":
            return {"value": [{"err": None, "confirmationStatus": confirmation_status}]}
        return transaction

    monkeypatch.setattr(solana_payments, "_rpc", fake_rpc)


def test_rpc_verification_accepts_exact_confirmed_transfer(monkeypatch) -> None:
    install_rpc(monkeypatch, rpc_result())
    proof = solana_payments.verify_solana_transfer(
        signature=SIGNATURE, sender=SENDER, recipient=RECIPIENT, lamports=125, memo=MEMO
    )
    assert proof.slot == 456
    assert proof.sender == SENDER
    assert proof.recipient == RECIPIENT


@pytest.mark.parametrize(
    ("transaction", "detail"),
    [
        (rpc_result(recipient="9" * 44), "amount or school wallet"),
        (rpc_result(lamports=124), "amount or school wallet"),
        (rpc_result(memo="wrong"), "memo does not match"),
        (rpc_result(signer=False), "did not sign"),
    ],
)
def test_rpc_verification_rejects_mismatched_evidence(monkeypatch, transaction, detail) -> None:
    install_rpc(monkeypatch, transaction)
    with pytest.raises(HTTPException, match=detail):
        solana_payments.verify_solana_transfer(
            signature=SIGNATURE,
            sender=SENDER,
            recipient=RECIPIENT,
            lamports=125,
            memo=MEMO,
        )


def test_rpc_verification_requires_confirmed_commitment(monkeypatch) -> None:
    install_rpc(monkeypatch, rpc_result(), confirmation_status="processed")
    with pytest.raises(HTTPException, match="not confirmed"):
        solana_payments.verify_solana_transfer(
            signature=SIGNATURE,
            sender=SENDER,
            recipient=RECIPIENT,
            lamports=125,
            memo=MEMO,
        )
