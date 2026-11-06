import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.models import AuditEvent

router = APIRouter(prefix="/api/v1/audit-events", tags=["audit"])


@router.get("")
def list_audit_events(
    school_id: uuid.UUID,
    limit: int = 200,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("audit:read")),
):
    context.assert_school(school_id)
    limit = min(max(limit, 1), 500)
    return session.scalars(
        select(AuditEvent)
        .where(AuditEvent.school_id == school_id)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
    ).all()
