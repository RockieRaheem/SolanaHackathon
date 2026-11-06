import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Literal, cast

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from harambeeone_api.config import get_settings
from harambeeone_api.database import get_session
from harambeeone_api.models import SchoolMembership

Role = Literal["owner", "bursar", "cashier", "auditor"]
Permission = Literal[
    "school:read",
    "school:manage",
    "periods:read",
    "periods:manage",
    "periods:reopen",
    "students:read",
    "students:write",
    "fees:read",
    "fees:write",
    "payments:read",
    "payments:write",
    "reconciliation:read",
    "reconciliation:write",
    "reports:read",
    "audit:read",
    "sponsors:read",
    "sponsors:write",
    "support:read",
    "support:write",
    "support:settle",
    "support:approve",
    "integrations:read",
    "integrations:manage",
]

ALL_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        "school:read",
        "school:manage",
        "periods:read",
        "periods:manage",
        "periods:reopen",
        "students:read",
        "students:write",
        "fees:read",
        "fees:write",
        "payments:read",
        "payments:write",
        "reconciliation:read",
        "reconciliation:write",
        "reports:read",
        "audit:read",
        "sponsors:read",
        "sponsors:write",
        "support:read",
        "support:write",
        "support:settle",
        "support:approve",
        "integrations:read",
        "integrations:manage",
    }
)
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    "owner": ALL_PERMISSIONS,
    "bursar": ALL_PERMISSIONS
    - {"sponsors:write", "periods:reopen", "support:approve", "integrations:manage"},
    "cashier": frozenset(
        {
            "school:read",
            "periods:read",
            "students:read",
            "fees:read",
            "payments:read",
            "payments:write",
            "support:read",
            "support:settle",
        }
    ),
    "auditor": frozenset(
        {
            "school:read",
            "periods:read",
            "students:read",
            "fees:read",
            "payments:read",
            "reconciliation:read",
            "reports:read",
            "audit:read",
            "sponsors:read",
            "support:read",
            "integrations:read",
        }
    ),
}
ROLE_ALIASES = {"owner_bursar": "owner"}


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID
    email: str | None


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    issuer = f"{str(get_settings().supabase_url).rstrip('/')}/auth/v1"
    return PyJWKClient(
        f"{issuer}/.well-known/jwks.json",
        cache_jwk_set=True,
        lifespan=600,
        timeout=5,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise _unauthorized("Sign in required")
    token = token.strip()
    issuer = f"{str(get_settings().supabase_url).rstrip('/')}/auth/v1"

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        return AuthenticatedUser(id=uuid.UUID(claims["sub"]), email=claims.get("email"))
    except ExpiredSignatureError as error:
        raise _unauthorized("Your session has expired. Please sign in again.") from error
    except ImmatureSignatureError as error:
        raise _unauthorized(
            "Your session is not active yet. Check your device time and try again."
        ) from error
    except PyJWKClientConnectionError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secure sign-in verification is temporarily unavailable. Please try again.",
        ) from error
    except (InvalidTokenError, PyJWKClientError, KeyError, TypeError, ValueError) as error:
        raise _unauthorized("We could not verify your session. Please sign in again.") from error


@dataclass(frozen=True)
class SchoolContext:
    user: AuthenticatedUser
    school_id: uuid.UUID
    role: Role

    @property
    def actor(self) -> str:
        return self.user.email or str(self.user.id)

    def assert_school(self, requested_school_id: uuid.UUID) -> None:
        if requested_school_id != self.school_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this institution",
            )


def get_school_context(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    active_school_id: Annotated[uuid.UUID | None, Header(alias="X-School-ID")] = None,
) -> SchoolContext:
    membership_query = select(SchoolMembership).where(SchoolMembership.auth_user_id == user.id)
    if active_school_id is not None:
        membership_query = membership_query.where(SchoolMembership.school_id == active_school_id)
    membership = session.scalar(
        membership_query.order_by(SchoolMembership.created_at, SchoolMembership.id)
    )
    if membership is None:
        if active_school_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the selected school section",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Complete institution setup before using the bursar workspace",
        )
    role_name = ROLE_ALIASES.get(membership.role, membership.role)
    if role_name not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your institution role is not recognized",
        )
    return SchoolContext(user=user, school_id=membership.school_id, role=cast(Role, role_name))


def require_permission(permission: Permission):
    def authorize(
        context: Annotated[SchoolContext, Depends(get_school_context)],
    ) -> SchoolContext:
        if permission not in ROLE_PERMISSIONS[context.role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your institution role does not permit this action",
            )
        return context

    return authorize
