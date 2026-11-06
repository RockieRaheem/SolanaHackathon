import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from harambeeone_api.auth import (
    AuthenticatedUser,
    SchoolContext,
    get_current_user,
    require_permission,
)
from harambeeone_api.database import get_session
from harambeeone_api.models import AuditEvent, SchoolMembership, StaffInvitation
from harambeeone_api.schemas import (
    StaffInvitationAccept,
    StaffInvitationCreate,
    StaffRoleUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["staff access"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _owner(context: SchoolContext) -> None:
    if context.role != "owner":
        raise HTTPException(
            status_code=403, detail="Only the section owner can manage staff access"
        )


@router.get("/staff-access")
def list_staff_access(
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
):
    _owner(context)
    now = datetime.now(UTC)
    members = session.scalars(
        select(SchoolMembership)
        .where(SchoolMembership.school_id == context.school_id)
        .order_by(SchoolMembership.created_at, SchoolMembership.id)
    ).all()
    invitations = session.scalars(
        select(StaffInvitation)
        .where(StaffInvitation.school_id == context.school_id)
        .order_by(StaffInvitation.created_at.desc())
    ).all()
    return {
        "members": [
            {
                "id": row.id,
                "user_id": row.auth_user_id,
                "email": row.member_email,
                "role": row.role,
                "is_current_user": row.auth_user_id == context.user.id,
                "created_at": row.created_at,
            }
            for row in members
        ],
        "invitations": [
            {
                "id": row.id,
                "email": row.invited_email,
                "role": row.role,
                "status": "expired"
                if row.status == "pending" and _utc(row.expires_at) <= now
                else row.status,
                "expires_at": row.expires_at,
                "created_at": row.created_at,
            }
            for row in invitations
        ],
    }


@router.post("/staff-invitations", status_code=status.HTTP_201_CREATED)
def create_staff_invitation(
    payload: StaffInvitationCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
):
    _owner(context)
    email = str(payload.email).strip().casefold()
    existing = session.scalar(
        select(SchoolMembership.id).where(
            SchoolMembership.school_id == context.school_id,
            SchoolMembership.member_email == email,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="This person already has access")
    now = datetime.now(UTC)
    pending = session.scalars(
        select(StaffInvitation).where(
            StaffInvitation.school_id == context.school_id,
            StaffInvitation.invited_email == email,
            StaffInvitation.status == "pending",
        )
    ).all()
    for row in pending:
        row.status = "revoked"
        row.revoked_at = now
    if pending:
        session.flush()
    token = secrets.token_urlsafe(32)
    invitation = StaffInvitation(
        school_id=context.school_id,
        invited_email=email,
        role=payload.role,
        token_hash=_hash(token),
        expires_at=now + timedelta(hours=72),
        created_by_user_id=context.user.id,
        created_by=context.actor,
    )
    session.add(invitation)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="staff_invitation",
            entity_id=invitation.id,
            action="created",
            actor=context.actor,
            summary=f"Invited {email} as {payload.role} for 72 hours",
        )
    )
    session.commit()
    return {
        "id": invitation.id,
        "email": email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "claim_path": f"/staff/accept?token={token}",
    }


@router.post("/staff-invitations/accept")
def accept_staff_invitation(
    payload: StaffInvitationAccept,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    invitation = session.scalar(
        select(StaffInvitation)
        .where(StaffInvitation.token_hash == _hash(payload.token))
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Staff invitation not found")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Staff invitation has already been used")
    now = datetime.now(UTC)
    if _utc(invitation.expires_at) <= now:
        invitation.status = "expired"
        session.commit()
        raise HTTPException(status_code=410, detail="Staff invitation has expired")
    email = (user.email or "").strip().casefold()
    if email != invitation.invited_email:
        raise HTTPException(
            status_code=403,
            detail=f"Sign in with the invited address {invitation.invited_email}",
        )
    membership = SchoolMembership(
        school_id=invitation.school_id,
        auth_user_id=user.id,
        member_email=email,
        role=invitation.role,
    )
    session.add(membership)
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = now
    session.flush()
    session.add(
        AuditEvent(
            school_id=invitation.school_id,
            entity_type="school_membership",
            entity_id=membership.id,
            action="accepted",
            actor=email,
            summary=f"Accepted {invitation.role} access to the school section",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="This account already has access") from error
    return {"school_id": invitation.school_id, "href": "/dashboard"}


@router.patch("/staff-memberships/{membership_id}")
def update_staff_role(
    membership_id: uuid.UUID,
    payload: StaffRoleUpdate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
):
    _owner(context)
    membership = session.scalar(
        select(SchoolMembership).where(
            SchoolMembership.id == membership_id,
            SchoolMembership.school_id == context.school_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Staff membership not found")
    if membership.role in {"owner", "owner_bursar"}:
        raise HTTPException(status_code=409, detail="Owner access cannot be changed here")
    previous = membership.role
    membership.role = payload.role
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="school_membership",
            entity_id=membership.id,
            action="role_changed",
            actor=context.actor,
            summary=f"Changed staff role from {previous} to {payload.role}",
        )
    )
    session.commit()
    return {"id": membership.id, "role": membership.role}


@router.delete("/staff-memberships/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_staff_access(
    membership_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
):
    _owner(context)
    membership = session.scalar(
        select(SchoolMembership).where(
            SchoolMembership.id == membership_id,
            SchoolMembership.school_id == context.school_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Staff membership not found")
    if membership.role in {"owner", "owner_bursar"} or membership.auth_user_id == context.user.id:
        raise HTTPException(status_code=409, detail="Owner access cannot be revoked here")
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="school_membership",
            entity_id=membership.id,
            action="revoked",
            actor=context.actor,
            summary=(
                f"Revoked {membership.role} access for "
                f"{membership.member_email or membership.auth_user_id}"
            ),
        )
    )
    session.delete(membership)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/staff-invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_staff_invitation(
    invitation_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
):
    _owner(context)
    invitation = session.scalar(
        select(StaffInvitation).where(
            StaffInvitation.id == invitation_id,
            StaffInvitation.school_id == context.school_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Staff invitation not found")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending invitations can be revoked")
    invitation.status = "revoked"
    invitation.revoked_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="staff_invitation",
            entity_id=invitation.id,
            action="revoked",
            actor=context.actor,
            summary=f"Revoked staff invitation for {invitation.invited_email}",
        )
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
