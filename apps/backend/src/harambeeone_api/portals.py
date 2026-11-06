import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from harambeeone_api.auth import AuthenticatedUser, get_current_user, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AuditEvent,
    DonorProfile,
    GuardianAccountLink,
    GuardianInvitation,
    GuardianLink,
    Person,
    PortalProfile,
    School,
    SchoolMembership,
    Student,
)
from harambeeone_api.schemas import (
    DonorProfileCreate,
    GuardianInvitationAccept,
    GuardianInvitationCreate,
    PortalPreferenceUpdate,
)
from harambeeone_api.support_notifications import emit_support_notification

router = APIRouter(prefix="/api/v1", tags=["portal access"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _display_name(user: AuthenticatedUser) -> str:
    return (user.email or "HarambeeOne user").split("@", 1)[0].replace(".", " ").title()


def _ensure_profile(
    session: Session,
    user: AuthenticatedUser,
    *,
    display_name: str | None = None,
    preferred_workspace: str | None = None,
) -> PortalProfile:
    profile = session.get(PortalProfile, user.id)
    if profile is None:
        profile = PortalProfile(
            auth_user_id=user.id,
            display_name=display_name or _display_name(user),
            preferred_workspace=preferred_workspace,
        )
        session.add(profile)
    else:
        if display_name:
            profile.display_name = display_name
        if preferred_workspace and profile.preferred_workspace is None:
            profile.preferred_workspace = preferred_workspace
    return profile


def _portal_payload(user: AuthenticatedUser, session: Session) -> dict:
    profile = session.get(PortalProfile, user.id)
    membership_rows = session.execute(
        select(SchoolMembership, School)
        .join(School, School.id == SchoolMembership.school_id)
        .where(SchoolMembership.auth_user_id == user.id)
    ).all()
    guardian_rows = session.execute(
        select(GuardianAccountLink, School)
        .join(School, School.id == GuardianAccountLink.school_id)
        .where(GuardianAccountLink.auth_user_id == user.id)
        .order_by(School.name)
    ).all()
    donor = session.get(DonorProfile, user.id)
    portals: list[dict] = []
    for membership, school in membership_rows:
        portals.append(
            {
                "type": "school",
                "label": f"{school.name} · {school.unit_name}",
                "detail": (
                    f"{membership.role.replace('_', ' ').title()} · Separate financial records"
                ),
                "href": f"/api/workspace/select?school_id={school.id}&next=/dashboard",
                "school_id": school.id,
                "role": membership.role,
            }
        )
    if guardian_rows:
        school_names = sorted({school.name for _link, school in guardian_rows})
        portals.append(
            {
                "type": "guardian",
                "label": "Guardian workspace",
                "detail": f"{len(guardian_rows)} linked learner account"
                f"{'s' if len(guardian_rows) != 1 else ''} · {', '.join(school_names)}",
                "href": "/guardian",
            }
        )
    if donor:
        portals.append(
            {
                "type": "donor",
                "label": "Donor workspace",
                "detail": "Contributions, receipts and campaign updates",
                "href": "/donor",
            }
        )
    available_types = {item["type"] for item in portals}
    preferred = profile.preferred_workspace if profile else None
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": profile.display_name if profile else _display_name(user),
        "preferred_workspace": preferred if preferred in available_types else None,
        "portals": portals,
    }


@router.get("/me/portals")
def get_my_portals(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return _portal_payload(user, session)


@router.patch("/me/portal-preference")
def update_portal_preference(
    payload: PortalPreferenceUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    context = _portal_payload(user, session)
    available = {item["type"] for item in context["portals"]}
    if payload.preferred_workspace and payload.preferred_workspace not in available:
        raise HTTPException(
            status_code=403, detail="That workspace is not available to this account"
        )
    profile = _ensure_profile(session, user)
    profile.preferred_workspace = payload.preferred_workspace
    session.commit()
    return _portal_payload(user, session)


@router.post("/me/donor-profile", status_code=status.HTTP_201_CREATED)
def activate_donor_profile(
    payload: DonorProfileCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    donor = session.get(DonorProfile, user.id)
    created = donor is None
    if donor is None:
        donor = DonorProfile(auth_user_id=user.id)
        session.add(donor)
    donor.display_name = payload.display_name.strip()
    donor.show_public_name = payload.show_public_name
    _ensure_profile(
        session,
        user,
        display_name=payload.display_name.strip(),
        preferred_workspace="donor",
    )
    session.commit()
    return {
        "created": created,
        "display_name": donor.display_name,
        "show_public_name": donor.show_public_name,
        "href": "/donor",
    }


@router.post("/support/guardian-invitations", status_code=status.HTTP_201_CREATED)
def create_guardian_invitation(
    payload: GuardianInvitationCreate,
    session: Session = Depends(get_session),
    context=Depends(require_permission("support:write")),
):
    context.assert_school(payload.school_id)
    row = session.execute(
        select(GuardianLink, Person, Student)
        .join(Person, Person.id == GuardianLink.person_id)
        .join(Student, Student.id == GuardianLink.student_id)
        .where(
            GuardianLink.id == payload.guardian_link_id,
            Student.school_id == context.school_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Guardian link not found")
    guardian, person, _student = row
    if not person.email:
        raise HTTPException(
            status_code=422,
            detail="Add a verified guardian email before creating portal access",
        )
    existing_link = session.scalar(
        select(GuardianAccountLink).where(GuardianAccountLink.guardian_link_id == guardian.id)
    )
    if existing_link:
        raise HTTPException(status_code=409, detail="This guardian already has portal access")
    pending = session.scalars(
        select(GuardianInvitation).where(
            GuardianInvitation.guardian_link_id == guardian.id,
            GuardianInvitation.status == "pending",
        )
    ).all()
    now = datetime.now(UTC)
    for invitation in pending:
        invitation.status = "revoked"
        invitation.revoked_at = now
    token = secrets.token_urlsafe(32)
    invitation = GuardianInvitation(
        school_id=context.school_id,
        guardian_link_id=guardian.id,
        token_hash=_token_hash(token),
        invited_email=person.email.strip().casefold(),
        expires_at=now + timedelta(hours=72),
        created_by=context.actor,
    )
    session.add(invitation)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="guardian_invitation",
            entity_id=invitation.id,
            action="created",
            actor=context.actor,
            summary="Created a 72-hour guardian portal invitation",
        )
    )
    emit_support_notification(
        session,
        school_id=context.school_id,
        recipient_type="guardian",
        recipient_email=invitation.invited_email,
        event_type="guardian_invited",
        title="Your school invited you to a secure guardian workspace",
        body="Sign in with this email and use the one-time claim link supplied by the school.",
        href="/guardian/claim",
        related_type="guardian_invitation",
        related_id=invitation.id,
        dedup_key=f"guardian-invitation:{invitation.id}:created",
    )
    session.commit()
    return {
        "id": invitation.id,
        "guardian_link_id": guardian.id,
        "invited_email": invitation.invited_email,
        "expires_at": invitation.expires_at,
        "claim_token": token,
        "claim_path": f"/guardian/claim?token={token}",
    }


@router.post("/guardian/invitations/accept")
def accept_guardian_invitation(
    payload: GuardianInvitationAccept,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    invitation = session.scalar(
        select(GuardianInvitation)
        .where(GuardianInvitation.token_hash == _token_hash(payload.token))
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Guardian invitation not found")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Guardian invitation has already been used")
    now = datetime.now(UTC)
    if _utc(invitation.expires_at) <= now:
        invitation.status = "expired"
        session.commit()
        raise HTTPException(status_code=410, detail="Guardian invitation has expired")
    if not user.email or user.email.strip().casefold() != invitation.invited_email:
        raise HTTPException(
            status_code=403,
            detail=f"Sign in with the invited address {invitation.invited_email}",
        )
    guardian = session.get(GuardianLink, invitation.guardian_link_id)
    person = session.get(Person, guardian.person_id) if guardian else None
    if guardian is None or person is None:
        raise HTTPException(status_code=409, detail="Guardian record is no longer available")
    link = GuardianAccountLink(
        auth_user_id=user.id,
        school_id=invitation.school_id,
        guardian_link_id=guardian.id,
        invitation_id=invitation.id,
    )
    session.add(link)
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = now
    name = " ".join(
        part for part in (person.first_name, person.middle_name, person.last_name) if part
    )
    _ensure_profile(session, user, display_name=name, preferred_workspace="guardian")
    session.flush()
    session.add(
        AuditEvent(
            school_id=invitation.school_id,
            entity_type="guardian_account_link",
            entity_id=link.id,
            action="accepted",
            actor=context_actor(user),
            summary="Guardian accepted verified portal access",
        )
    )
    emit_support_notification(
        session,
        school_id=invitation.school_id,
        recipient_type="guardian",
        recipient_auth_user_id=user.id,
        event_type="guardian_linked",
        title="Guardian workspace connected",
        body="You can now review only the learner accounts explicitly linked by the school.",
        href="/guardian",
        related_type="guardian_account_link",
        related_id=link.id,
        dedup_key=f"guardian-link:{link.id}:accepted:guardian",
    )
    emit_support_notification(
        session,
        school_id=invitation.school_id,
        recipient_type="school",
        event_type="guardian_linked",
        title="Guardian accepted portal access",
        body="The verified guardian can now receive private referrals for the linked learner.",
        href="/support-admin",
        related_type="guardian_account_link",
        related_id=link.id,
        dedup_key=f"guardian-link:{link.id}:accepted:school",
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Guardian portal access already exists"
        ) from error
    return {"linked": True, "href": "/guardian"}


def context_actor(user: AuthenticatedUser) -> str:
    return user.email or str(user.id)


@router.get("/guardian/learners")
def list_guardian_learners(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(GuardianAccountLink, GuardianLink, Student, Person, School)
        .join(GuardianLink, GuardianLink.id == GuardianAccountLink.guardian_link_id)
        .join(Student, Student.id == GuardianLink.student_id)
        .join(Person, Person.id == Student.person_id)
        .join(School, School.id == GuardianAccountLink.school_id)
        .where(GuardianAccountLink.auth_user_id == user.id)
        .order_by(School.name, Person.first_name, Person.last_name)
    ).all()
    return [
        {
            "student_id": student.id,
            "school_id": link.school_id,
            "school_name": school.name,
            "learner_name": " ".join(
                part for part in (person.first_name, person.middle_name, person.last_name) if part
            ),
            "admission_no": student.admission_no,
            "relationship": guardian.relationship,
            "is_primary": guardian.is_primary,
            "verified_at": link.verified_at,
        }
        for link, guardian, student, person, school in rows
    ]


@router.get("/donor/profile")
def get_donor_profile(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    donor = session.get(DonorProfile, user.id)
    if donor is None:
        raise HTTPException(status_code=404, detail="Donor profile is not active")
    return {
        "display_name": donor.display_name,
        "show_public_name": donor.show_public_name,
        "created_at": donor.created_at,
    }
