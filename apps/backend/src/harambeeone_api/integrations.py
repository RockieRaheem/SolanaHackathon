import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.config import get_settings
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AuditEvent,
    IntegrationClient,
    IntegrationDelivery,
    IntegrationExchangeLog,
    IntegrationImportBatch,
    IntegrationOutboxEvent,
    IntegrationWebhookSubscription,
    LearnerIdentity,
    LearnerTransferCase,
    School,
    Student,
)
from harambeeone_api.schemas import (
    IntegrationClientCreate,
    IntegrationImportCreate,
    IntegrationImportReview,
    IntegrationWebhookCreate,
)

router = APIRouter(tags=["integrations"])
SCHEMA_VERSION = "harambeeone.v1"


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _owner(context: SchoolContext) -> None:
    if context.role != "owner":
        raise HTTPException(
            status_code=403, detail="Only the section owner can manage integrations"
        )


def _new_api_key() -> tuple[str, str, str]:
    token = f"hbo_live_{secrets.token_urlsafe(32)}"
    return token, token[:20], _hash(token)


def _new_signing_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


@dataclass(frozen=True)
class IntegrationContext:
    client_id: uuid.UUID
    school_id: uuid.UUID
    client_name: str
    purpose: str
    lawful_basis: str
    scopes: frozenset[str]
    allowed_fields: frozenset[str]

    @property
    def actor(self) -> str:
        return f"integration:{self.client_name}:{self.client_id}"


def get_integration_context(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> IntegrationContext:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token.startswith("hbo_live_"):
        raise HTTPException(status_code=401, detail="A valid integration credential is required")
    client = session.scalar(
        select(IntegrationClient)
        .where(IntegrationClient.key_prefix == token[:20])
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        client is None
        or client.status != "active"
        or not hmac.compare_digest(client.secret_hash, _hash(token))
        or (client.expires_at is not None and _utc(client.expires_at) <= now)
    ):
        raise HTTPException(status_code=401, detail="Integration credential is invalid or expired")
    window = client.request_window_started_at
    if window is None or _utc(window) <= now - timedelta(minutes=1):
        client.request_window_started_at = now
        client.request_count = 1
    else:
        if client.request_count >= client.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Integration rate limit exceeded")
        client.request_count += 1
    client.last_used_at = now
    session.commit()
    return IntegrationContext(
        client_id=client.id,
        school_id=client.school_id,
        client_name=client.name,
        purpose=client.purpose,
        lawful_basis=client.lawful_basis,
        scopes=frozenset(json.loads(client.scopes_json)),
        allowed_fields=frozenset(json.loads(client.allowed_fields_json)),
    )


def require_integration_scope(scope: str):
    def authorize(context: IntegrationContext = Depends(get_integration_context)):
        if scope not in context.scopes:
            raise HTTPException(status_code=403, detail=f"Credential lacks the {scope} scope")
        return context

    return authorize


def enqueue_integration_event(
    session: Session,
    *,
    school_id: uuid.UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict,
    correlation_id: str,
) -> IntegrationOutboxEvent:
    event = IntegrationOutboxEvent(
        school_id=school_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload_json=_json(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": None,
                "event_type": event_type,
                "occurred_at": datetime.now(UTC).isoformat(),
                "correlation_id": correlation_id,
                "data": payload,
            }
        ),
        correlation_id=correlation_id,
    )
    session.add(event)
    session.flush()
    envelope = json.loads(event.payload_json)
    envelope["event_id"] = str(event.id)
    event.payload_json = _json(envelope)
    subscriptions = session.scalars(
        select(IntegrationWebhookSubscription).where(
            IntegrationWebhookSubscription.school_id == school_id,
            IntegrationWebhookSubscription.status == "active",
        )
    ).all()
    for subscription in subscriptions:
        if event_type in json.loads(subscription.event_types_json):
            session.add(
                IntegrationDelivery(
                    school_id=school_id,
                    event_id=event.id,
                    subscription_id=subscription.id,
                    next_attempt_at=datetime.now(UTC),
                )
            )
    return event


def _safe_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Webhook URL must be a valid HTTPS URL")
    development_local = get_settings().app_environment == "development" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if parsed.scheme != "https" and not development_local:
        raise HTTPException(status_code=422, detail="Webhook URL must use HTTPS")
    if development_local:
        return
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise HTTPException(status_code=422, detail="Webhook host could not be resolved") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise HTTPException(
                status_code=422, detail="Webhook URL cannot target a private network"
            )


def _post_webhook(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
    class RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with build_opener(RejectRedirects).open(request, timeout=8) as response:
            return response.status, response.read(500).decode(errors="replace")
    except HTTPError as error:
        return error.code, error.read(500).decode(errors="replace")
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(str(error)) from error


def _deliver(session: Session, delivery: IntegrationDelivery) -> IntegrationDelivery:
    if delivery.status == "delivered":
        return delivery
    subscription = session.get(IntegrationWebhookSubscription, delivery.subscription_id)
    event = session.get(IntegrationOutboxEvent, delivery.event_id)
    if subscription is None or event is None or subscription.status != "active":
        delivery.status = "abandoned"
        delivery.last_error = "Webhook subscription is no longer active"
        session.commit()
        return delivery
    try:
        _safe_webhook_url(subscription.url)
    except HTTPException as error:
        delivery.status = "abandoned"
        delivery.last_error = str(error.detail)[:500]
        delivery.last_attempt_at = datetime.now(UTC)
        session.commit()
        return delivery
    body = event.payload_json.encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        subscription.signing_secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.now(UTC)
    try:
        code, response_text = _post_webhook(
            subscription.url,
            body,
            {
                "Content-Type": "application/json",
                "User-Agent": "HarambeeOne-Webhooks/1.0",
                "X-Harambee-Event-ID": str(event.id),
                "X-Harambee-Timestamp": timestamp,
                "X-Harambee-Signature": f"v1={signature}",
            },
        )
        delivery.last_response_code = code
        if 200 <= code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
            delivery.last_error = None
            delivery.next_attempt_at = None
        else:
            delivery.status = "abandoned" if delivery.attempt_count >= 8 else "failed"
            delivery.last_error = f"HTTP {code}: {response_text}"[:500]
    except RuntimeError as error:
        delivery.status = "abandoned" if delivery.attempt_count >= 8 else "failed"
        delivery.last_error = str(error)[:500]
    if delivery.status == "failed":
        delay = min(2**delivery.attempt_count, 60)
        delivery.next_attempt_at = datetime.now(UTC) + timedelta(minutes=delay)
    session.commit()
    return delivery


def deliver_outbox_events(bind, event_ids: list[uuid.UUID]) -> None:
    """Deliver committed events after the originating request has safely completed."""
    with Session(bind, expire_on_commit=False) as session:
        deliveries = session.scalars(
            select(IntegrationDelivery).where(
                IntegrationDelivery.event_id.in_(event_ids),
                IntegrationDelivery.status == "pending",
            )
        ).all()
        for delivery in deliveries:
            _deliver(session, delivery)


def _client_payload(client: IntegrationClient) -> dict:
    return {
        "id": client.id,
        "name": client.name,
        "key_prefix": f"{client.key_prefix}…",
        "scopes": json.loads(client.scopes_json),
        "allowed_fields": json.loads(client.allowed_fields_json),
        "purpose": client.purpose,
        "lawful_basis": client.lawful_basis,
        "status": client.status,
        "rate_limit_per_minute": client.rate_limit_per_minute,
        "created_at": client.created_at,
        "last_used_at": client.last_used_at,
        "expires_at": client.expires_at,
    }


@router.get("/api/v1/integrations")
def integration_overview(
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:read")),
):
    clients = session.scalars(
        select(IntegrationClient)
        .where(IntegrationClient.school_id == context.school_id)
        .order_by(IntegrationClient.created_at.desc())
    ).all()
    webhooks = session.scalars(
        select(IntegrationWebhookSubscription)
        .where(IntegrationWebhookSubscription.school_id == context.school_id)
        .order_by(IntegrationWebhookSubscription.created_at.desc())
    ).all()
    imports = session.scalars(
        select(IntegrationImportBatch)
        .where(IntegrationImportBatch.school_id == context.school_id)
        .order_by(IntegrationImportBatch.created_at.desc())
        .limit(50)
    ).all()
    deliveries = session.scalars(
        select(IntegrationDelivery)
        .where(IntegrationDelivery.school_id == context.school_id)
        .order_by(IntegrationDelivery.created_at.desc())
        .limit(50)
    ).all()
    logs = session.scalars(
        select(IntegrationExchangeLog)
        .where(IntegrationExchangeLog.school_id == context.school_id)
        .order_by(IntegrationExchangeLog.created_at.desc())
        .limit(50)
    ).all()
    client_names = {row.id: row.name for row in clients}
    return {
        "can_manage": context.role == "owner",
        "clients": [_client_payload(row) for row in clients],
        "webhooks": [
            {
                "id": row.id,
                "client_id": row.integration_client_id,
                "client_name": client_names.get(row.integration_client_id, "Integration"),
                "url": row.url,
                "event_types": json.loads(row.event_types_json),
                "status": row.status,
                "created_at": row.created_at,
                "rotated_at": row.rotated_at,
            }
            for row in webhooks
        ],
        "imports": [
            {
                "id": row.id,
                "client_name": client_names.get(row.integration_client_id, "Integration"),
                "resource_type": row.resource_type,
                "status": row.status,
                "record_count": row.record_count,
                "issues": json.loads(row.issues_json),
                "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
            }
            for row in imports
        ],
        "deliveries": [
            {
                "id": row.id,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "response_code": row.last_response_code,
                "last_error": row.last_error,
                "created_at": row.created_at,
                "last_attempt_at": row.last_attempt_at,
            }
            for row in deliveries
        ],
        "exchange_logs": [
            {
                "id": row.id,
                "client_name": client_names.get(row.integration_client_id, "Integration"),
                "direction": row.direction,
                "resource_type": row.resource_type,
                "record_count": row.record_count,
                "fields": json.loads(row.fields_json),
                "purpose": row.purpose,
                "lawful_basis": row.lawful_basis,
                "correlation_id": row.correlation_id,
                "outcome": row.outcome,
                "created_at": row.created_at,
            }
            for row in logs
        ],
    }


@router.post("/api/v1/integrations/clients", status_code=201)
def create_integration_client(
    payload: IntegrationClientCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    token, prefix, secret_hash = _new_api_key()
    client = IntegrationClient(
        school_id=context.school_id,
        name=payload.name.strip(),
        key_prefix=prefix,
        secret_hash=secret_hash,
        scopes_json=_json(payload.scopes),
        allowed_fields_json=_json(payload.allowed_fields),
        purpose=payload.purpose.strip(),
        lawful_basis=payload.lawful_basis.strip(),
        rate_limit_per_minute=payload.rate_limit_per_minute,
        expires_at=payload.expires_at,
        created_by=context.actor,
    )
    session.add(client)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="An integration with this name already exists"
        ) from error
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_client",
            entity_id=client.id,
            action="created",
            actor=context.actor,
            summary=f"Created integration {client.name} with scopes {', '.join(payload.scopes)}",
        )
    )
    session.commit()
    return {**_client_payload(client), "api_key": token}


@router.post("/api/v1/integrations/clients/{client_id}/rotate")
def rotate_integration_client(
    client_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    client = session.scalar(
        select(IntegrationClient).where(
            IntegrationClient.id == client_id,
            IntegrationClient.school_id == context.school_id,
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if client.status != "active":
        raise HTTPException(status_code=409, detail="Revoked integrations cannot be rotated")
    token, prefix, secret_hash = _new_api_key()
    client.key_prefix = prefix
    client.secret_hash = secret_hash
    client.request_count = 0
    client.request_window_started_at = None
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_client",
            entity_id=client.id,
            action="credential_rotated",
            actor=context.actor,
            summary=f"Rotated credential for {client.name}; the previous key is invalid",
        )
    )
    session.commit()
    return {**_client_payload(client), "api_key": token}


@router.delete("/api/v1/integrations/clients/{client_id}", status_code=204)
def revoke_integration_client(
    client_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    client = session.scalar(
        select(IntegrationClient).where(
            IntegrationClient.id == client_id,
            IntegrationClient.school_id == context.school_id,
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    client.status = "revoked"
    client.revoked_at = datetime.now(UTC)
    subscriptions = session.scalars(
        select(IntegrationWebhookSubscription).where(
            IntegrationWebhookSubscription.integration_client_id == client.id
        )
    ).all()
    for subscription in subscriptions:
        subscription.status = "disabled"
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_client",
            entity_id=client.id,
            action="revoked",
            actor=context.actor,
            summary=f"Revoked integration {client.name} and disabled its webhooks",
        )
    )
    session.commit()
    return Response(status_code=204)


@router.post("/api/v1/integrations/webhooks", status_code=201)
def create_webhook(
    payload: IntegrationWebhookCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    client = session.scalar(
        select(IntegrationClient).where(
            IntegrationClient.id == payload.integration_client_id,
            IntegrationClient.school_id == context.school_id,
            IntegrationClient.status == "active",
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Active integration not found")
    url = str(payload.url)
    _safe_webhook_url(url)
    secret = _new_signing_secret()
    subscription = IntegrationWebhookSubscription(
        school_id=context.school_id,
        integration_client_id=client.id,
        url=url,
        signing_secret=secret,
        event_types_json=_json(payload.event_types),
        created_by=context.actor,
    )
    session.add(subscription)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This webhook URL is already registered"
        ) from error
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_webhook",
            entity_id=subscription.id,
            action="created",
            actor=context.actor,
            summary=f"Created signed webhook for {client.name}",
        )
    )
    session.commit()
    return {"id": subscription.id, "url": subscription.url, "signing_secret": secret}


@router.post("/api/v1/integrations/webhooks/{subscription_id}/rotate")
def rotate_webhook_secret(
    subscription_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    subscription = session.scalar(
        select(IntegrationWebhookSubscription).where(
            IntegrationWebhookSubscription.id == subscription_id,
            IntegrationWebhookSubscription.school_id == context.school_id,
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    secret = _new_signing_secret()
    subscription.signing_secret = secret
    subscription.rotated_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_webhook",
            entity_id=subscription.id,
            action="secret_rotated",
            actor=context.actor,
            summary="Rotated webhook signing secret",
        )
    )
    session.commit()
    return {"id": subscription.id, "signing_secret": secret}


@router.delete("/api/v1/integrations/webhooks/{subscription_id}", status_code=204)
def disable_webhook(
    subscription_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    subscription = session.scalar(
        select(IntegrationWebhookSubscription).where(
            IntegrationWebhookSubscription.id == subscription_id,
            IntegrationWebhookSubscription.school_id == context.school_id,
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    subscription.status = "disabled"
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_webhook",
            entity_id=subscription.id,
            action="disabled",
            actor=context.actor,
            summary="Disabled integration webhook delivery",
        )
    )
    session.commit()
    return Response(status_code=204)


@router.post("/api/v1/integrations/webhooks/{subscription_id}/test")
def test_webhook(
    subscription_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    subscription = session.scalar(
        select(IntegrationWebhookSubscription).where(
            IntegrationWebhookSubscription.id == subscription_id,
            IntegrationWebhookSubscription.school_id == context.school_id,
            IntegrationWebhookSubscription.status == "active",
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Active webhook not found")
    event = IntegrationOutboxEvent(
        school_id=context.school_id,
        event_type="integration.test",
        aggregate_type="integration_webhook",
        aggregate_id=subscription.id,
        payload_json="{}",
        correlation_id=f"test-{uuid.uuid4().hex}",
    )
    session.add(event)
    session.flush()
    event.payload_json = _json(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(event.id),
            "event_type": "integration.test",
            "occurred_at": datetime.now(UTC).isoformat(),
            "correlation_id": event.correlation_id,
            "data": {"message": "HarambeeOne webhook connection test"},
        }
    )
    delivery = IntegrationDelivery(
        school_id=context.school_id,
        event_id=event.id,
        subscription_id=subscription.id,
        next_attempt_at=datetime.now(UTC),
    )
    session.add(delivery)
    session.commit()
    _deliver(session, delivery)
    return {
        "id": delivery.id,
        "status": delivery.status,
        "response_code": delivery.last_response_code,
        "error": delivery.last_error,
    }


@router.post("/api/v1/integrations/deliveries/{delivery_id}/retry")
def retry_delivery(
    delivery_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    delivery = session.scalar(
        select(IntegrationDelivery)
        .where(
            IntegrationDelivery.id == delivery_id,
            IntegrationDelivery.school_id == context.school_id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    if delivery.status == "abandoned":
        delivery.status = "failed"
    delivery = _deliver(session, delivery)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_delivery",
            entity_id=delivery.id,
            action="retried",
            actor=context.actor,
            summary=f"Retried webhook delivery; outcome {delivery.status}",
        )
    )
    session.commit()
    return {"id": delivery.id, "status": delivery.status, "attempt_count": delivery.attempt_count}


def _exchange_log(
    session: Session,
    context: IntegrationContext,
    *,
    direction: str,
    resource_type: str,
    correlation_id: str,
    record_count: int,
    payload_hash: str,
    outcome: str,
    idempotency_key: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        IntegrationExchangeLog(
            school_id=context.school_id,
            integration_client_id=context.client_id,
            direction=direction,
            resource_type=resource_type,
            purpose=context.purpose,
            lawful_basis=context.lawful_basis,
            fields_json=_json(sorted(context.allowed_fields)),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            record_count=record_count,
            payload_hash=payload_hash,
            outcome=outcome,
            detail=detail,
            actor=context.actor,
        )
    )


def _export_envelope(
    school: School, resource_type: str, records: list[dict], correlation_id: str
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "resource_type": resource_type,
        "generated_at": datetime.now(UTC).isoformat(),
        "correlation_id": correlation_id,
        "organization": {
            "id": school.organization_id,
            "name": school.organization_name,
            "emis_code": school.organization.emis_code if school.organization else school.emis_code,
        },
        "unit": {
            "id": school.id,
            "name": school.unit_name,
            "type": school.unit_type,
        },
        "records": records,
    }


@router.get("/api/integration/v1/learners")
def export_learners(
    limit: int = Query(default=100, ge=1, le=500),
    cursor: uuid.UUID | None = Query(default=None),
    correlation_header: str | None = Header(default=None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session),
    context: IntegrationContext = Depends(require_integration_scope("learners:read")),
):
    school = session.scalar(
        select(School)
        .where(School.id == context.school_id)
        .options(selectinload(School.organization))
    )
    query = (
        select(Student)
        .where(Student.school_id == context.school_id)
        .options(
            selectinload(Student.person),
            selectinload(Student.enrollments),
            selectinload(Student.guardians),
        )
        .order_by(Student.id)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(Student.id > cursor)
    rows = list(session.scalars(query).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    records = []
    for student in rows:
        record = {
            "stable_learner_id": student.learner_identity_id,
            "local_student_id": student.id,
            "admission_no": student.admission_no,
            "status": student.status,
        }
        if "demographics" in context.allowed_fields:
            record["demographics"] = {
                "first_name": student.person.first_name,
                "middle_name": student.person.middle_name,
                "last_name": student.person.last_name,
                "date_of_birth": student.person.date_of_birth,
                "gender": student.gender,
                "nationality": student.nationality,
            }
        if "placement" in context.allowed_fields:
            enrollment = max(
                student.enrollments,
                key=lambda row: (row.academic_year, row.term, str(row.id)),
                default=None,
            )
            if enrollment:
                session.refresh(enrollment, attribute_names=["academic_class", "stream"])
                record["placement"] = {
                    "period_id": enrollment.period_id,
                    "academic_year": enrollment.academic_year,
                    "term": enrollment.term,
                    "class_id": enrollment.class_id,
                    "canonical_class_code": enrollment.academic_class.canonical_code,
                    "class_name": enrollment.academic_class.name,
                    "stream_id": enrollment.stream_id,
                    "stream_name": enrollment.stream.name if enrollment.stream else None,
                }
        if "guardian_contact" in context.allowed_fields:
            primary = next((row for row in student.guardians if row.is_primary), None)
            if primary:
                session.refresh(primary, attribute_names=["person"])
                record["guardian"] = {
                    "relationship": primary.relationship,
                    "first_name": primary.person.first_name,
                    "last_name": primary.person.last_name,
                    "phone": primary.person.phone,
                    "email": primary.person.email,
                }
        records.append(record)
    correlation_id = (correlation_header or f"exp-{uuid.uuid4().hex}")[:64]
    envelope = _export_envelope(school, "learners", records, correlation_id)
    envelope["next_cursor"] = str(rows[-1].id) if has_more and rows else None
    payload_hash = _hash(_json(envelope))
    _exchange_log(
        session,
        context,
        direction="export",
        resource_type="learners",
        correlation_id=correlation_id,
        record_count=len(records),
        payload_hash=payload_hash,
        outcome="completed",
    )
    session.commit()
    return envelope


@router.get("/api/integration/v1/transfers")
def export_transfers(
    limit: int = Query(default=100, ge=1, le=500),
    correlation_header: str | None = Header(default=None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session),
    context: IntegrationContext = Depends(require_integration_scope("transfers:read")),
):
    school = session.scalar(
        select(School)
        .where(School.id == context.school_id)
        .options(selectinload(School.organization))
    )
    rows = session.scalars(
        select(LearnerTransferCase)
        .where(
            or_(
                LearnerTransferCase.source_school_id == context.school_id,
                LearnerTransferCase.target_school_id == context.school_id,
            )
        )
        .order_by(LearnerTransferCase.created_at.desc())
        .limit(limit)
    ).all()
    records = []
    for row in rows:
        record = {
            "transfer_id": row.id,
            "reference": row.reference,
            "stable_learner_id": session.get(Student, row.source_student_id).learner_identity_id,
            "source_unit_id": row.source_school_id,
            "target_unit_id": row.target_school_id,
            "status": row.status,
            "purpose": row.purpose,
            "consent": {
                "method": row.consent_method,
                "reference": row.consent_reference,
                "recorded_at": row.consent_recorded_at,
            },
            "created_at": row.created_at,
            "decided_at": row.decided_at,
        }
        if "demographics" in context.allowed_fields:
            record["learner"] = {
                "first_name": row.learner_first_name,
                "middle_name": row.learner_middle_name,
                "last_name": row.learner_last_name,
                "date_of_birth": row.learner_date_of_birth,
                "gender": row.learner_gender,
            }
        records.append(record)
    correlation_id = (correlation_header or f"exp-{uuid.uuid4().hex}")[:64]
    envelope = _export_envelope(school, "learner_transfers", records, correlation_id)
    payload_hash = _hash(_json(envelope))
    _exchange_log(
        session,
        context,
        direction="export",
        resource_type="learner_transfers",
        correlation_id=correlation_id,
        record_count=len(records),
        payload_hash=payload_hash,
        outcome="completed",
    )
    session.commit()
    return envelope


@router.post("/api/integration/v1/imports", status_code=202)
def import_learners(
    payload: IntegrationImportCreate,
    correlation_header: str | None = Header(default=None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session),
    context: IntegrationContext = Depends(require_integration_scope("imports:write")),
):
    canonical = payload.model_dump(mode="json")
    payload_json = _json(canonical)
    payload_hash = _hash(payload_json)
    existing = session.scalar(
        select(IntegrationImportBatch).where(
            IntegrationImportBatch.integration_client_id == context.client_id,
            IntegrationImportBatch.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was reused with new data")
        return {
            "id": existing.id,
            "status": existing.status,
            "issues": json.loads(existing.issues_json),
            "idempotent_replay": True,
        }
    school = session.get(School, context.school_id)
    issues: list[dict] = []
    seen: set[uuid.UUID] = set()
    for index, record in enumerate(payload.records):
        if record.stable_learner_id in seen:
            issues.append({"record": index, "code": "duplicate_stable_id", "severity": "conflict"})
            continue
        seen.add(record.stable_learner_id)
        source = session.get(School, record.source_unit_id)
        if (
            record.organization_id != school.organization_id
            or source is None
            or source.organization_id != school.organization_id
        ):
            issues.append(
                {"record": index, "code": "organization_mismatch", "severity": "conflict"}
            )
            continue
        identity = session.get(LearnerIdentity, record.stable_learner_id)
        if identity is None:
            issues.append({"record": index, "code": "unknown_stable_learner", "severity": "review"})
            continue
        if identity.organization_id != school.organization_id:
            issues.append(
                {"record": index, "code": "identity_organization_mismatch", "severity": "conflict"}
            )
            continue
        local = session.scalar(
            select(Student)
            .where(
                Student.school_id == record.source_unit_id,
                Student.learner_identity_id == record.stable_learner_id,
            )
            .options(selectinload(Student.person), selectinload(Student.enrollments))
        )
        if local is None:
            issues.append({"record": index, "code": "source_record_missing", "severity": "review"})
            continue
        conflicts = []
        if local.admission_no != record.admission_no:
            conflicts.append("admission_no")
        if record.first_name and local.person.first_name.casefold() != record.first_name.casefold():
            conflicts.append("first_name")
        if record.last_name and local.person.last_name.casefold() != record.last_name.casefold():
            conflicts.append("last_name")
        if local.status != record.status:
            conflicts.append("status")
        if record.canonical_class_code:
            latest = max(
                local.enrollments,
                key=lambda row: (row.academic_year, row.term, str(row.id)),
                default=None,
            )
            if latest:
                session.refresh(latest, attribute_names=["academic_class"])
            if (
                latest is None
                or latest.academic_class.canonical_code != record.canonical_class_code
            ):
                conflicts.append("canonical_class_code")
        if conflicts:
            issues.append(
                {
                    "record": index,
                    "code": "trusted_record_conflict",
                    "severity": "conflict",
                    "fields": conflicts,
                }
            )
    status = "quarantined" if any(row["severity"] == "conflict" for row in issues) else "validated"
    batch = IntegrationImportBatch(
        school_id=context.school_id,
        integration_client_id=context.client_id,
        resource_type=payload.resource_type,
        idempotency_key=payload.idempotency_key,
        payload_json=payload_json,
        payload_hash=payload_hash,
        issues_json=_json(issues),
        status=status,
        record_count=len(payload.records),
    )
    session.add(batch)
    session.flush()
    correlation_id = (correlation_header or f"imp-{uuid.uuid4().hex}")[:64]
    _exchange_log(
        session,
        context,
        direction="import",
        resource_type=payload.resource_type,
        correlation_id=correlation_id,
        idempotency_key=payload.idempotency_key,
        record_count=len(payload.records),
        payload_hash=payload_hash,
        outcome=status,
        detail=f"{len(issues)} validation issue(s)",
    )
    session.commit()
    return {"id": batch.id, "status": batch.status, "issues": issues, "idempotent_replay": False}


@router.post("/api/v1/integrations/imports/{batch_id}/review")
def review_import(
    batch_id: uuid.UUID,
    payload: IntegrationImportReview,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("integrations:manage")),
):
    _owner(context)
    batch = session.scalar(
        select(IntegrationImportBatch)
        .where(
            IntegrationImportBatch.id == batch_id,
            IntegrationImportBatch.school_id == context.school_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch.status in {"acknowledged", "rejected"}:
        raise HTTPException(status_code=409, detail="Import batch has already been reviewed")
    batch.status = "acknowledged" if payload.action == "acknowledge" else "rejected"
    batch.reviewed_by = context.actor
    batch.reviewed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="integration_import",
            entity_id=batch.id,
            action=batch.status,
            actor=context.actor,
            summary=(
                f"{batch.status.capitalize()} staged {batch.resource_type} import; "
                "trusted records were not overwritten"
            ),
        )
    )
    session.commit()
    return {"id": batch.id, "status": batch.status}
