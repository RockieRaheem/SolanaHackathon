import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from harambeeone_api import auth

ISSUER = "https://project.supabase.co/auth/v1"


def _token(
    private_key,
    user_id: uuid.UUID,
    *,
    expires_at: float,
    issuer: str = ISSUER,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": "authenticated",
            "email": "bursar@example.test",
            "exp": int(expires_at),
            "iat": now,
            "iss": issuer,
            "sub": str(user_id),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )


def _configure(monkeypatch, public_key):
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(supabase_url="https://project.supabase.co"),
    )
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        ),
    )


def test_verifies_supabase_es256_access_token_locally(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    _configure(monkeypatch, private_key.public_key())
    user_id = uuid.uuid4()

    user = auth.get_current_user(
        f"Bearer {_token(private_key, user_id, expires_at=time.time() + 300)}"
    )

    assert user.id == user_id
    assert user.email == "bursar@example.test"


def test_reports_expired_session_clearly(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    _configure(monkeypatch, private_key.public_key())

    with pytest.raises(HTTPException) as caught:
        auth.get_current_user(
            f"Bearer {_token(private_key, uuid.uuid4(), expires_at=time.time() - 60)}"
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Your session has expired. Please sign in again."


def test_rejects_token_from_another_issuer(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    _configure(monkeypatch, private_key.public_key())

    with pytest.raises(HTTPException) as caught:
        auth.get_current_user(
            "Bearer "
            + _token(
                private_key,
                uuid.uuid4(),
                expires_at=time.time() + 300,
                issuer="https://attacker.example/auth/v1",
            )
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "We could not verify your session. Please sign in again."
