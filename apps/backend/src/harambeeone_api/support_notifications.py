import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    SchoolMembership,
    SupportNotification,
    SupportNotificationOutbox,
    SupportNotificationRead,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def emit_support_notification(
    session: Session,
    *,
    school_id: uuid.UUID,
    recipient_type: str,
    event_type: str,
    title: str,
    body: str,
    href: str,
    related_type: str,
    related_id: uuid.UUID,
    dedup_key: str,
    recipient_auth_user_id: uuid.UUID | None = None,
    recipient_email: str | None = None,
) -> SupportNotification:
    """Add one durable notification and provider-neutral delivery job to this transaction."""
    existing = session.scalar(
        select(SupportNotification).where(SupportNotification.dedup_key == dedup_key)
    )
    if existing is not None:
        return existing
    notification = SupportNotification(
        school_id=school_id,
        recipient_type=recipient_type,
        recipient_auth_user_id=recipient_auth_user_id,
        recipient_email=recipient_email.strip().casefold() if recipient_email else None,
        event_type=event_type,
        title=title,
        body=body,
        href=href,
        related_type=related_type,
        related_id=related_id,
        dedup_key=dedup_key,
    )
    session.add(notification)
    session.flush()
    session.add(
        SupportNotificationOutbox(
            notification_id=notification.id,
            payload_json=json.dumps(
                {
                    "notification_id": str(notification.id),
                    "recipient_type": recipient_type,
                    "recipient_user_id": (
                        str(recipient_auth_user_id) if recipient_auth_user_id else None
                    ),
                    "recipient_email": notification.recipient_email,
                    "event_type": event_type,
                    "title": title,
                    "body": body,
                    "href": href,
                }
            ),
        )
    )
    return notification


def _visible_query(user: AuthenticatedUser, session: Session):
    school_ids = select(SchoolMembership.school_id).where(SchoolMembership.auth_user_id == user.id)
    email = user.email.strip().casefold() if user.email else ""
    return select(SupportNotification).where(
        or_(
            SupportNotification.recipient_auth_user_id == user.id,
            and_(
                SupportNotification.recipient_auth_user_id.is_(None),
                SupportNotification.recipient_email == email,
            ),
            and_(
                SupportNotification.recipient_type == "school",
                SupportNotification.school_id.in_(school_ids),
            ),
        )
    )


def _notification_payload(notification: SupportNotification, read_ids: set[uuid.UUID]) -> dict:
    return {
        "id": notification.id,
        "recipient_type": notification.recipient_type,
        "event_type": notification.event_type,
        "title": notification.title,
        "body": notification.body,
        "href": notification.href,
        "related_type": notification.related_type,
        "related_id": notification.related_id,
        "created_at": notification.created_at,
        "read": notification.id in read_ids,
    }


@router.get("")
def list_notifications(
    limit: int = 50,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    limit = max(1, min(limit, 100))
    rows = session.scalars(
        _visible_query(user, session).order_by(SupportNotification.created_at.desc()).limit(limit)
    ).all()
    read_ids = set(
        session.scalars(
            select(SupportNotificationRead.notification_id).where(
                SupportNotificationRead.auth_user_id == user.id,
                SupportNotificationRead.notification_id.in_([item.id for item in rows]),
            )
        ).all()
    )
    items = [_notification_payload(item, read_ids) for item in rows]
    return {"items": items, "unread_count": sum(not item["read"] for item in items)}


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    notification = session.scalar(
        _visible_query(user, session).where(SupportNotification.id == notification_id)
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    read = session.scalar(
        select(SupportNotificationRead).where(
            SupportNotificationRead.notification_id == notification.id,
            SupportNotificationRead.auth_user_id == user.id,
        )
    )
    if read is None:
        session.add(
            SupportNotificationRead(
                notification_id=notification.id,
                auth_user_id=user.id,
                read_at=datetime.now(UTC),
            )
        )
        session.commit()
    return {"id": notification.id, "read": True}


@router.post("/read-all")
def mark_all_notifications_read(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.scalars(_visible_query(user, session)).all()
    existing = set(
        session.scalars(
            select(SupportNotificationRead.notification_id).where(
                SupportNotificationRead.auth_user_id == user.id
            )
        ).all()
    )
    now = datetime.now(UTC)
    session.add_all(
        SupportNotificationRead(
            notification_id=item.id,
            auth_user_id=user.id,
            read_at=now,
        )
        for item in rows
        if item.id not in existing
    )
    session.commit()
    return {"read": len(rows)}
