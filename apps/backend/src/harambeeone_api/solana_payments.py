import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from harambeeone_api.config import get_settings

BASE58_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")
MEMO_PROGRAM_IDS = {
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
}


class SolanaIntentCreate(BaseModel):
    payment_destination_id: str
    idempotency_key: str = Field(min_length=8, max_length=80)
    donor_display_name: str | None = Field(default=None, max_length=100)
    amount: int = Field(gt=0)


class SolanaIntentConfirm(BaseModel):
    transaction_signature: str = Field(min_length=64, max_length=128)
    sender_address: str = Field(min_length=32, max_length=64)

    @field_validator("transaction_signature", "sender_address")
    @classmethod
    def validate_base58(cls, value: str) -> str:
        value = value.strip()
        if not BASE58_PATTERN.fullmatch(value):
            raise ValueError("must be valid base58")
        return value


@dataclass(frozen=True)
class VerifiedSolanaTransfer:
    signature: str
    sender: str
    recipient: str
    lamports: int
    memo: str
    slot: int
    block_time: datetime


def _rpc(method: str, params: list) -> dict:
    settings = get_settings()
    try:
        response = httpx.post(
            str(settings.solana_rpc_url),
            json={"jsonrpc": "2.0", "id": "harambeeone", "method": method, "params": params},
            timeout=12.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Solana confirmation is temporarily unavailable. Your transfer is safe; "
                "retry confirmation shortly."
            ),
        ) from error
    if payload.get("error"):
        raise HTTPException(status_code=502, detail="Solana RPC rejected the confirmation request")
    return payload.get("result")


def verify_solana_transfer(
    *, signature: str, sender: str, recipient: str, lamports: int, memo: str
) -> VerifiedSolanaTransfer:
    statuses = _rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
    status = (statuses or {}).get("value", [None])[0]
    if not status or status.get("err") is not None:
        raise HTTPException(status_code=409, detail="The Solana transaction has not succeeded")
    if status.get("confirmationStatus") not in {"confirmed", "finalized"}:
        raise HTTPException(status_code=409, detail="The Solana transaction is not confirmed yet")
    transaction = _rpc(
        "getTransaction",
        [
            signature,
            {
                "commitment": "confirmed",
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 1,
            },
        ],
    )
    if not transaction or (transaction.get("meta") or {}).get("err") is not None:
        raise HTTPException(
            status_code=409, detail="The confirmed Solana transaction is unavailable"
        )
    message = transaction.get("transaction", {}).get("message", {})
    signer_keys = {
        item.get("pubkey")
        for item in message.get("accountKeys", [])
        if isinstance(item, dict) and item.get("signer")
    }
    if sender not in signer_keys:
        raise HTTPException(
            status_code=422, detail="The connected wallet did not sign this transfer"
        )
    transfer_matches = False
    memo_matches = False
    for instruction in message.get("instructions", []):
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info", {}) if isinstance(parsed, dict) else {}
        if (
            instruction.get("program") == "system"
            and isinstance(parsed, dict)
            and parsed.get("type") == "transfer"
            and info.get("source") == sender
            and info.get("destination") == recipient
            and int(info.get("lamports", -1)) == lamports
        ):
            transfer_matches = True
        if instruction.get("programId") in MEMO_PROGRAM_IDS and parsed == memo:
            memo_matches = True
    if not transfer_matches:
        raise HTTPException(
            status_code=422,
            detail=("Transaction amount or school wallet does not match this checkout"),
        )
    if not memo_matches:
        raise HTTPException(status_code=422, detail="Transaction memo does not match this checkout")
    block_time = transaction.get("blockTime")
    if not isinstance(block_time, int):
        raise HTTPException(status_code=409, detail="Transaction time is not available yet")
    return VerifiedSolanaTransfer(
        signature=signature,
        sender=sender,
        recipient=recipient,
        lamports=lamports,
        memo=memo,
        slot=int(transaction["slot"]),
        block_time=datetime.fromtimestamp(block_time, UTC),
    )
