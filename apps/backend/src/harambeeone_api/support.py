import base64
import binascii
import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from harambeeone_api.auth import (
    AuthenticatedUser,
    SchoolContext,
    get_current_user,
    require_permission,
)
from harambeeone_api.config import get_settings
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AuditEvent,
    DonorProfile,
    GuardianAccountLink,
    GuardianLink,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    Requirement,
    School,
    StellarAnchor,
    Student,
    StudentRequirement,
    SupportAiReview,
    SupportAttestation,
    SupportCase,
    SupportConsent,
    SupportPaymentDestination,
    SupportPledge,
    SupportReceiptReissue,
    SupportReceiptSequence,
    SupportReferral,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import (
    GuardianAcknowledgementCreate,
    GuardianSupportCaseSave,
    SupportAiReviewCreate,
    SupportAttestationCreate,
    SupportAttestationReview,
    SupportCaseCreate,
    SupportCaseReviewDecision,
    SupportConsentCreate,
    SupportPaymentDestinationCreate,
    SupportPaymentDestinationDecision,
    SupportPledgeCreate,
    SupportPledgeReverse,
    SupportPledgeVerify,
    SupportReceiptReissueCreate,
    SupportReferralConsent,
    SupportReferralCreate,
)
from harambeeone_api.support_assistants import (
    finish_assistant_usage,
    gemma_response_text,
    parse_gemma_json,
    request_gemma_json,
    start_assistant_usage,
)
from harambeeone_api.support_notifications import emit_support_notification

router = APIRouter(prefix="/api/v1/support", tags=["learner support"])

PRIVACY_NOTICE_VERSION = "2026-10-v1"
PRIVACY_NOTICE = (
    "The school will use the learner's private identity only to verify eligibility and post "
    "support to the school account. Donors see an anonymous campaign code, need category, "
    "target, verified totals and redacted outcomes—not the learner or guardian identity. "
    "Gemma and processing outside Uganda are optional. Consent may be withdrawn at any time."
)


def _guardian_referral(session: Session, referral_id: uuid.UUID, user_id: uuid.UUID):
    referral = session.scalar(
        select(SupportReferral)
        .join(
            GuardianAccountLink,
            GuardianAccountLink.guardian_link_id == SupportReferral.guardian_link_id,
        )
        .where(SupportReferral.id == referral_id, GuardianAccountLink.auth_user_id == user_id)
    )
    if referral is None:
        raise HTTPException(status_code=404, detail="Support referral not found")
    return referral


def _referral_payload(session: Session, referral: SupportReferral) -> dict:
    student = session.get(Student, referral.student_id)
    person = session.get(Person, student.person_id) if student else None
    school = session.get(School, referral.school_id)
    support_case = session.scalar(select(SupportCase).where(SupportCase.referral_id == referral.id))
    return {
        "id": referral.id,
        "school_id": referral.school_id,
        "school_name": school.name if school else "School",
        "student_id": referral.student_id,
        "learner_name": (f"{person.first_name} {person.last_name}" if person else "Linked learner"),
        "admission_no": student.admission_no if student else None,
        "outstanding_snapshot": referral.outstanding_snapshot,
        "overdue_since": referral.overdue_since,
        "days_overdue_snapshot": referral.days_overdue_snapshot,
        "priority_band": referral.priority_band,
        "priority_reasons": json.loads(referral.priority_reasons),
        "status": referral.status,
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
        "privacy_notice": PRIVACY_NOTICE,
        "anonymous_publication": referral.anonymous_publication,
        "gemma_processing": referral.gemma_processing,
        "cross_border_processing": referral.cross_border_processing,
        "child_assent_status": referral.child_assent_status,
        "child_assent_reason": referral.child_assent_reason,
        "consented_at": referral.consented_at,
        "withdrawn_at": referral.withdrawn_at,
        "case": _guardian_case_payload(session, support_case) if support_case else None,
    }


def _obligation_balance(
    session: Session,
    *,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    student_id: uuid.UUID,
    requirement_assignment_id: uuid.UUID | None,
) -> tuple[Decimal, str]:
    if requirement_assignment_id:
        row = session.execute(
            select(StudentRequirement, Requirement)
            .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
            .where(
                StudentRequirement.id == requirement_assignment_id,
                StudentRequirement.student_id == student_id,
                Requirement.school_id == school_id,
                Requirement.period_id == period_id,
                Requirement.requirement_type.in_(("payment", "school_item")),
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=422, detail="Requirement does not belong to learner")
        assignment, requirement = row
        paid = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.requirement_assignment_id == assignment.id
            )
        ) or Decimal("0")
        return max(assignment.expected_amount - paid, Decimal("0")), requirement.name
    outstanding = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.school_id == school_id,
            LedgerEntry.period_id == period_id,
            LedgerEntry.student_id == student_id,
        )
    ) or Decimal("0")
    return max(outstanding, Decimal("0")), "School fees / general balance"


def _case_live_limit(session: Session, support_case: SupportCase) -> Decimal:
    outstanding, _label = _obligation_balance(
        session,
        school_id=support_case.school_id,
        period_id=support_case.period_id,
        student_id=support_case.student_id,
        requirement_assignment_id=support_case.requirement_assignment_id,
    )
    return outstanding + _money_total(session, support_case.id, "verified")


def _refresh_case_target(session: Session, support_case: SupportCase, actor: str) -> Decimal:
    live_limit = _case_live_limit(session, support_case)
    if live_limit > 0 and support_case.target_amount > live_limit:
        old_target = support_case.target_amount
        support_case.target_amount = live_limit
        session.add(
            AuditEvent(
                school_id=support_case.school_id,
                entity_type="support_case",
                entity_id=support_case.id,
                action="target_reduced",
                actor=actor,
                summary=f"Reduced target from UGX {old_target:,.0f} to UGX {live_limit:,.0f}",
            )
        )
    elif live_limit <= 0 and support_case.status in {
        "draft",
        "changes_requested",
        "submitted",
        "review",
        "approved",
        "published",
    }:
        support_case.status = "closed"
        support_case.closed_at = datetime.now(UTC)
    return live_limit


def _guardian_case_payload(session: Session, support_case: SupportCase) -> dict:
    live_limit = _case_live_limit(session, support_case)
    return {
        "id": support_case.id,
        "public_code": support_case.public_code,
        "requirement_assignment_id": support_case.requirement_assignment_id,
        "title": support_case.title,
        "public_summary": support_case.public_summary,
        "private_context": support_case.private_context,
        "need_category": support_case.need_category,
        "target_amount": support_case.target_amount,
        "verified_amount": _money_total(session, support_case.id, "verified"),
        "pending_amount": _money_total(session, support_case.id, "pending"),
        "live_limit": live_limit,
        "status": support_case.status,
        "review_notes": support_case.review_notes,
        "submitted_at": support_case.submitted_at,
        "reviewed_at": support_case.reviewed_at,
    }


def _money_total(session: Session, case_id: uuid.UUID, *statuses: str) -> Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(SupportPledge.amount), 0)).where(
            SupportPledge.case_id == case_id,
            SupportPledge.status.in_(statuses),
        )
    ) or Decimal("0")


def _notify_guardian(
    session: Session,
    support_case: SupportCase,
    event_type: str,
    title: str,
    body: str,
    *,
    suffix: str = "",
) -> None:
    if support_case.guardian_auth_user_id is None:
        return
    emit_support_notification(
        session,
        school_id=support_case.school_id,
        recipient_type="guardian",
        recipient_auth_user_id=support_case.guardian_auth_user_id,
        event_type=event_type,
        title=title,
        body=body,
        href="/guardian",
        related_type="support_case",
        related_id=support_case.id,
        dedup_key=f"case:{support_case.id}:{event_type}:guardian{suffix}",
    )


def _notify_school(
    session: Session,
    support_case: SupportCase,
    event_type: str,
    title: str,
    body: str,
    *,
    suffix: str = "",
) -> None:
    emit_support_notification(
        session,
        school_id=support_case.school_id,
        recipient_type="school",
        event_type=event_type,
        title=title,
        body=body,
        href="/support-admin",
        related_type="support_case",
        related_id=support_case.id,
        dedup_key=f"case:{support_case.id}:{event_type}:school{suffix}",
    )


def _notify_case_donors(
    session: Session,
    support_case: SupportCase,
    event_type: str,
    title: str,
    body: str,
    *,
    suffix: str = "",
) -> None:
    donor_ids = set(
        session.scalars(
            select(SupportPledge.donor_auth_user_id).where(
                SupportPledge.case_id == support_case.id,
                SupportPledge.donor_auth_user_id.is_not(None),
            )
        ).all()
    )
    for donor_id in donor_ids:
        emit_support_notification(
            session,
            school_id=support_case.school_id,
            recipient_type="donor",
            recipient_auth_user_id=donor_id,
            event_type=event_type,
            title=title,
            body=body,
            href="/donor",
            related_type="support_case",
            related_id=support_case.id,
            dedup_key=f"case:{support_case.id}:{event_type}:donor:{donor_id}{suffix}",
        )


def _latest_review(session: Session, case_id: uuid.UUID) -> SupportAiReview | None:
    return session.scalar(
        select(SupportAiReview)
        .where(SupportAiReview.case_id == case_id, SupportAiReview.status == "completed")
        .order_by(SupportAiReview.created_at.desc())
        .limit(1)
    )


def _active_consent(session: Session, case_id: uuid.UUID) -> SupportConsent | None:
    return session.scalar(
        select(SupportConsent).where(
            SupportConsent.case_id == case_id, SupportConsent.status == "active"
        )
    )


def _assert_public_text(case: SupportCase, student: Student, person: Person, value: str) -> None:
    normalized = value.casefold()
    private_values = [
        student.admission_no,
        person.first_name,
        person.middle_name,
        person.last_name,
        student.learner_identification_number,
    ]
    for private_value in private_values:
        if (
            private_value
            and len(private_value.strip()) >= 3
            and private_value.casefold() in normalized
        ):
            raise HTTPException(
                status_code=422,
                detail="Public campaign text must not identify the learner",
            )


def _private_case(session: Session, case_id: uuid.UUID, school_id: uuid.UUID) -> SupportCase:
    support_case = session.scalar(
        select(SupportCase).where(SupportCase.id == case_id, SupportCase.school_id == school_id)
    )
    if support_case is None:
        raise HTTPException(status_code=404, detail="Support case not found")
    return support_case


def _public_campaign(session: Session, public_code: str) -> SupportCase:
    support_case = session.scalar(
        select(SupportCase).where(
            SupportCase.public_code == public_code.upper(),
            SupportCase.status.in_(("published", "funded", "closed")),
        )
    )
    if support_case is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return support_case


def _public_payload(session: Session, support_case: SupportCase, *, detail: bool) -> dict:
    verified = _money_total(session, support_case.id, "verified")
    pending = _money_total(session, support_case.id, "pending")
    school = session.get(School, support_case.school_id)
    payload = {
        "public_code": support_case.public_code,
        "title": support_case.title,
        "public_summary": support_case.public_summary,
        "need_category": support_case.need_category,
        "target_amount": support_case.target_amount,
        "verified_amount": verified,
        "pending_amount": pending,
        "remaining_amount": max(support_case.target_amount - verified, Decimal("0")),
        "currency": support_case.currency,
        "status": support_case.status,
        "school": school.name if school else "Verified participating school",
        "published_at": support_case.published_at,
        "privacy": "Learner identity is held privately by the school and is never published.",
    }
    if not detail:
        return payload
    review = _latest_review(session, support_case.id)
    attestations = session.scalars(
        select(SupportAttestation)
        .where(
            SupportAttestation.case_id == support_case.id,
            SupportAttestation.status == "approved",
            SupportAttestation.is_public.is_(True),
        )
        .order_by(SupportAttestation.verified_at.desc())
    ).all()
    payload["ai_review"] = None
    if review:
        result = json.loads(review.result_json)
        payload["ai_review"] = {
            "model": review.model_name,
            "observed_factors": result.get("observed_factors", []),
            "consistency_flags": result.get("consistency_flags", []),
            "recommended_action": result.get("recommended_action"),
        }
    payload["attestations"] = [
        {
            "type": item.attestation_type,
            "statement": item.redacted_statement,
            "attendance_band": item.attendance_band,
            "evidence_hash": item.evidence_hash,
            "verified_at": item.verified_at,
        }
        for item in attestations
    ]
    timeline = [
        {
            "type": "campaign_published",
            "title": "Campaign approved and published",
            "detail": "The school verified the obligation and opened this anonymous campaign.",
            "occurred_at": support_case.published_at,
        }
    ]
    if verified > 0:
        timeline.append(
            {
                "type": "funds_verified",
                "title": "School-confirmed contributions",
                "detail": f"UGX {verified:,.0f} has been received and posted to the obligation.",
                "occurred_at": max(
                    (
                        item.verified_at
                        for item in session.scalars(
                            select(SupportPledge).where(
                                SupportPledge.case_id == support_case.id,
                                SupportPledge.status.in_(("verified", "reversed")),
                            )
                        ).all()
                        if item.verified_at
                    ),
                    default=support_case.published_at,
                ),
            }
        )
    timeline.extend(
        {
            "type": f"outcome_{item.attestation_type}",
            "title": "Outcome evidence approved",
            "detail": item.redacted_statement,
            "occurred_at": item.reviewed_at or item.verified_at,
        }
        for item in reversed(attestations)
    )
    payload["timeline"] = timeline
    destinations = session.scalars(
        select(SupportPaymentDestination)
        .where(
            SupportPaymentDestination.school_id == support_case.school_id,
            SupportPaymentDestination.verification_status == "verified",
        )
        .order_by(SupportPaymentDestination.channel, SupportPaymentDestination.label)
    ).all()
    payload["payment_destinations"] = [
        {
            "id": item.id,
            "channel": item.channel,
            "label": item.label,
            "provider_name": item.provider_name,
            "account_name": item.account_name,
            "account_reference": item.account_reference,
            "instructions": item.instructions,
        }
        for item in destinations
    ]
    return payload


def _pledge_payload(pledge: SupportPledge) -> dict:
    return {
        "public_reference": pledge.public_reference,
        "status": pledge.status,
        "amount": pledge.amount,
        "currency": pledge.currency,
        "message": "Contribution is pending independent settlement verification by the school.",
    }


def _create_pledge(
    session: Session,
    *,
    public_code: str,
    payload: SupportPledgeCreate,
    donor_user_id: uuid.UUID | None,
) -> SupportPledge:
    support_case = session.scalar(
        select(SupportCase)
        .where(SupportCase.public_code == public_code.upper(), SupportCase.status == "published")
        .with_for_update()
    )
    if support_case is None:
        raise HTTPException(status_code=404, detail="Open campaign not found")
    existing = session.scalar(
        select(SupportPledge).where(
            SupportPledge.case_id == support_case.id,
            SupportPledge.idempotency_key == payload.idempotency_key.strip(),
        )
    )
    if existing:
        if (
            existing.amount != payload.amount
            or existing.external_reference != payload.external_reference.strip()
            or existing.payment_destination_id != payload.payment_destination_id
            or existing.donor_auth_user_id != donor_user_id
        ):
            raise HTTPException(status_code=409, detail="This checkout key was already used")
        return existing
    destination = session.scalar(
        select(SupportPaymentDestination).where(
            SupportPaymentDestination.id == payload.payment_destination_id,
            SupportPaymentDestination.school_id == support_case.school_id,
            SupportPaymentDestination.verification_status == "verified",
        )
    )
    if destination is None:
        raise HTTPException(status_code=422, detail="Choose a verified school payment destination")
    _refresh_case_target(session, support_case, "system:pledge-check")
    if support_case.status != "published":
        session.commit()
        raise HTTPException(status_code=409, detail="This campaign is no longer accepting support")
    reserved = _money_total(session, support_case.id, "pending", "verified")
    available = max(support_case.target_amount - reserved, Decimal("0"))
    if payload.amount > available:
        raise HTTPException(
            status_code=422,
            detail=f"Contribution exceeds the remaining campaign amount of UGX {available:,.0f}",
        )
    pledge = SupportPledge(
        case_id=support_case.id,
        school_id=support_case.school_id,
        payment_destination_id=destination.id,
        donor_auth_user_id=donor_user_id,
        idempotency_key=payload.idempotency_key.strip(),
        public_reference=f"HSP-{uuid.uuid4().hex[:16].upper()}",
        external_reference=payload.external_reference.strip(),
        donor_display_name=(payload.donor_display_name or "").strip() or None,
        amount=payload.amount,
        currency=support_case.currency,
    )
    session.add(pledge)
    try:
        session.flush()
        _notify_school(
            session,
            support_case,
            "pledge_created",
            "A contribution is awaiting verification",
            (
                f"{pledge.public_reference} for UGX {pledge.amount:,.0f} must be "
                "matched to school funds."
            ),
            suffix=f":{pledge.id}",
        )
        _notify_guardian(
            session,
            support_case,
            "pledge_created",
            "Support has been pledged",
            "A contribution is pending independent verification by the school.",
            suffix=f":{pledge.id}",
        )
        if donor_user_id:
            emit_support_notification(
                session,
                school_id=support_case.school_id,
                recipient_type="donor",
                recipient_auth_user_id=donor_user_id,
                event_type="pledge_created",
                title="Your contribution is awaiting school verification",
                body=(
                    f"Track {pledge.public_reference}; pending funds do not increase "
                    "the campaign total."
                ),
                href="/donor",
                related_type="support_pledge",
                related_id=pledge.id,
                dedup_key=f"pledge:{pledge.id}:created:donor",
            )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        replay = session.scalar(
            select(SupportPledge).where(
                SupportPledge.case_id == support_case.id,
                SupportPledge.idempotency_key == payload.idempotency_key.strip(),
            )
        )
        if replay:
            return replay
        raise HTTPException(
            status_code=409, detail="This settlement reference already exists"
        ) from error
    return pledge


def _next_support_receipt(session: Session, school_id: uuid.UUID) -> str:
    counter = session.scalar(
        select(SupportReceiptSequence)
        .where(SupportReceiptSequence.school_id == school_id)
        .with_for_update()
    )
    if counter is None:
        counter = SupportReceiptSequence(school_id=school_id, next_number=1)
        session.add(counter)
        session.flush()
    number = counter.next_number
    counter.next_number += 1
    return f"H1S-{datetime.now(UTC).year}-{school_id.hex[:4].upper()}-{number:06d}"


def _receipt_payload(
    session: Session, pledge: SupportPledge, *, include_settlement_reference: bool
) -> dict:
    support_case = session.get(SupportCase, pledge.case_id)
    payment = session.get(Payment, pledge.payment_id) if pledge.payment_id else None
    school = session.get(School, pledge.school_id)
    destination = (
        session.get(SupportPaymentDestination, pledge.payment_destination_id)
        if pledge.payment_destination_id
        else None
    )
    if support_case is None or payment is None or school is None:
        raise HTTPException(
            status_code=409, detail="Receipt is not available for this contribution"
        )
    return {
        "receipt_no": payment.receipt_no,
        "issued_at": pledge.verified_at,
        "school_name": school.name,
        "school_district": school.district,
        "campaign_code": support_case.public_code,
        "campaign_title": support_case.title,
        "need_category": support_case.need_category,
        "amount": pledge.amount,
        "currency": pledge.currency,
        "donor_name": pledge.donor_display_name or "Anonymous donor",
        "channel": destination.channel if destination else payment.channel,
        "provider_name": destination.provider_name if destination else None,
        "settlement_reference": pledge.external_reference if include_settlement_reference else None,
        "status": pledge.status,
        "allocation_statement": (
            "Posted to the verified school obligation for this anonymous campaign."
        ),
        "privacy_statement": "This receipt intentionally contains no learner or guardian identity.",
    }


def _call_gemma(
    *,
    case_payload: dict,
    evidence_image_base64: str | None,
    evidence_mime_type: str | None,
) -> tuple[str, dict]:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemma review is not configured. Add GEMINI_API_KEY to the server environment.",
        )
    prompt = (
        "You are the privacy-safe review assistant for a Ugandan school support programme. "
        "Use only the supplied anonymous financial facts and optional redacted evidence image. "
        "Do not infer identity, health, disability, gender, pregnancy, abuse, ethnicity "
        "or family details. Do not claim fraud or predict that a learner will drop out. "
        "Flag uncertainty for human review. "
        "Return JSON with exactly these keys: summary, risk_level, observed_factors, "
        "missing_information, consistency_flags, recommended_action, safe_public_summary. "
        "risk_level must be low, medium, high or review; list fields must contain short strings; "
        "safe_public_summary must be 20-500 characters and contain no invented facts.\n\n"
        f"Anonymous case facts: {json.dumps(case_payload, separators=(',', ':'))}"
    )
    parts: list[dict] = [{"text": prompt}]
    if evidence_image_base64 and evidence_mime_type:
        try:
            base64.b64decode(evidence_image_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise HTTPException(
                status_code=422, detail="Evidence image is not valid base64"
            ) from error
        parts.append(
            {
                "inline_data": {
                    "mime_type": evidence_mime_type,
                    "data": evidence_image_base64,
                }
            }
        )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
    ).encode()
    query = urlencode({"key": settings.gemini_api_key})
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemma_model}:generateContent?{query}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        api_result = request_gemma_json(request, timeout=35)
        text = gemma_response_text(api_result)
        result = parse_gemma_json(text)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemma could not complete the support review",
        ) from error
    required = {
        "summary",
        "risk_level",
        "observed_factors",
        "missing_information",
        "consistency_flags",
        "recommended_action",
        "safe_public_summary",
    }
    if not required.issubset(result) or result["risk_level"] not in {
        "low",
        "medium",
        "high",
        "review",
    }:
        raise HTTPException(status_code=502, detail="Gemma returned an invalid review structure")
    for key in ("observed_factors", "missing_information", "consistency_flags"):
        if not isinstance(result[key], list) or not all(
            isinstance(item, str) for item in result[key]
        ):
            raise HTTPException(
                status_code=502, detail="Gemma returned an invalid review structure"
            )
    if not 20 <= len(str(result["safe_public_summary"])) <= 500:
        raise HTTPException(status_code=502, detail="Gemma returned an invalid public summary")
    return settings.gemma_model, result


@router.get("/referral-candidates")
def list_referral_candidates(
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    from harambeeone_api.finance import list_arrears

    context.assert_school(school_id)
    arrears = list_arrears(school_id, period_id, None, session, context)
    referrals = {
        item.student_id: item
        for item in session.scalars(
            select(SupportReferral).where(
                SupportReferral.school_id == school_id,
                SupportReferral.period_id == period_id,
            )
        ).all()
    }
    rows = []
    for item in arrears.items:
        guardian_row = session.execute(
            select(GuardianLink, Person)
            .join(Person, Person.id == GuardianLink.person_id)
            .where(GuardianLink.student_id == item.student_id)
            .order_by(GuardianLink.is_primary.desc())
            .limit(1)
        ).one_or_none()
        guardian, guardian_person = guardian_row if guardian_row else (None, None)
        portal_linked = bool(
            guardian
            and session.scalar(
                select(GuardianAccountLink.id).where(
                    GuardianAccountLink.guardian_link_id == guardian.id
                )
            )
        )
        referral = referrals.get(item.student_id)
        band = (
            "urgent" if item.days_overdue >= 60 else "high" if item.days_overdue >= 30 else "watch"
        )
        rows.append(
            {
                **item.model_dump(),
                "priority_band": band,
                "priority_reasons": [
                    f"UGX {item.overdue_amount:,.0f} is overdue",
                    f"Oldest unpaid installment is {item.days_overdue} days overdue",
                ],
                "guardian_link_id": guardian.id if guardian else None,
                "guardian_email": guardian_person.email if guardian_person else None,
                "guardian_portal_linked": portal_linked,
                "referral_id": referral.id if referral else None,
                "referral_status": referral.status if referral else None,
            }
        )
    return {"privacy_notice_version": PRIVACY_NOTICE_VERSION, "items": rows}


@router.post("/referrals", status_code=status.HTTP_201_CREATED)
def create_support_referral(
    payload: SupportReferralCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    from harambeeone_api.finance import list_arrears

    context.assert_school(payload.school_id)
    resolve_period(session, school_id=context.school_id, period_id=payload.period_id, writable=True)
    account = next(
        (
            item
            for item in list_arrears(
                payload.school_id, payload.period_id, None, session, context
            ).items
            if item.student_id == payload.student_id
        ),
        None,
    )
    if account is None:
        raise HTTPException(status_code=422, detail="Learner has no overdue fee obligation")
    guardian = session.scalar(
        select(GuardianLink)
        .join(Student, Student.id == GuardianLink.student_id)
        .where(
            GuardianLink.id == payload.guardian_link_id,
            GuardianLink.student_id == payload.student_id,
            Student.school_id == context.school_id,
        )
    )
    if guardian is None:
        raise HTTPException(status_code=422, detail="Guardian does not belong to this learner")
    guardian_user_id = session.scalar(
        select(GuardianAccountLink.auth_user_id).where(
            GuardianAccountLink.guardian_link_id == guardian.id
        )
    )
    if not guardian_user_id:
        raise HTTPException(
            status_code=409,
            detail="Invite the guardian and wait for portal access before creating a referral",
        )
    band = (
        "urgent"
        if account.days_overdue >= 60
        else "high"
        if account.days_overdue >= 30
        else "watch"
    )
    referral = SupportReferral(
        school_id=context.school_id,
        period_id=payload.period_id,
        student_id=payload.student_id,
        guardian_link_id=guardian.id,
        outstanding_snapshot=account.overdue_amount,
        overdue_since=account.overdue_since,
        days_overdue_snapshot=account.days_overdue,
        priority_band=band,
        priority_reasons=json.dumps(
            [
                f"UGX {account.overdue_amount:,.0f} is overdue",
                f"Oldest unpaid installment is {account.days_overdue} days overdue",
            ]
        ),
        created_by=context.actor,
    )
    session.add(referral)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This learner already has a referral for the period"
        ) from error
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_referral",
            entity_id=referral.id,
            action="created",
            actor=context.actor,
            summary="Created a private arrears-based guardian referral",
        )
    )
    emit_support_notification(
        session,
        school_id=context.school_id,
        recipient_type="guardian",
        recipient_auth_user_id=guardian_user_id,
        event_type="referral_created",
        title="Your school has requested a private review",
        body=(
            "Review the verified balance and privacy choices before deciding whether "
            "to participate."
        ),
        href="/guardian",
        related_type="support_referral",
        related_id=referral.id,
        dedup_key=f"referral:{referral.id}:created:guardian",
    )
    session.commit()
    return _referral_payload(session, referral)


@router.get("/referrals")
def list_school_referrals(
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    context.assert_school(school_id)
    rows = session.scalars(
        select(SupportReferral)
        .where(
            SupportReferral.school_id == school_id,
            SupportReferral.period_id == period_id,
        )
        .order_by(SupportReferral.created_at.desc())
    ).all()
    return [_referral_payload(session, item) for item in rows]


@router.get("/guardian/referrals")
def list_guardian_referrals(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.scalars(
        select(SupportReferral)
        .join(
            GuardianAccountLink,
            GuardianAccountLink.guardian_link_id == SupportReferral.guardian_link_id,
        )
        .where(GuardianAccountLink.auth_user_id == user.id)
        .order_by(SupportReferral.created_at.desc())
    ).all()
    return [_referral_payload(session, item) for item in rows]


@router.get("/guardian/referrals/{referral_id}/obligations")
def list_guardian_referral_obligations(
    referral_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    if referral.status not in {"consented", "case_submitted"}:
        raise HTTPException(status_code=409, detail="Give active consent before drafting a case")
    general, general_label = _obligation_balance(
        session,
        school_id=referral.school_id,
        period_id=referral.period_id,
        student_id=referral.student_id,
        requirement_assignment_id=None,
    )
    requirement_rows = session.execute(
        select(StudentRequirement, Requirement)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(
            StudentRequirement.student_id == referral.student_id,
            Requirement.school_id == referral.school_id,
            Requirement.period_id == referral.period_id,
            Requirement.requirement_type.in_(("payment", "school_item")),
        )
        .order_by(Requirement.name)
    ).all()
    requirements = []
    for assignment, requirement in requirement_rows:
        outstanding, _label = _obligation_balance(
            session,
            school_id=referral.school_id,
            period_id=referral.period_id,
            student_id=referral.student_id,
            requirement_assignment_id=assignment.id,
        )
        if outstanding > 0:
            requirements.append(
                {
                    "id": assignment.id,
                    "label": requirement.name,
                    "outstanding": outstanding,
                    "suggested_category": requirement.category,
                }
            )
    return {
        "general": {"id": None, "label": general_label, "outstanding": general},
        "requirements": requirements,
    }


@router.post("/guardian/referrals/{referral_id}/case")
def save_guardian_support_case(
    referral_id: uuid.UUID,
    payload: GuardianSupportCaseSave,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    if referral.status not in {"consented", "case_submitted"}:
        raise HTTPException(status_code=409, detail="Active guardian consent is required")
    if not referral.anonymous_publication or referral.child_assent_status == "declined":
        raise HTTPException(status_code=409, detail="Publication consent is not active")
    resolve_period(
        session,
        school_id=referral.school_id,
        period_id=referral.period_id,
        writable=True,
    )
    outstanding, _label = _obligation_balance(
        session,
        school_id=referral.school_id,
        period_id=referral.period_id,
        student_id=referral.student_id,
        requirement_assignment_id=payload.requirement_assignment_id,
    )
    if outstanding <= 0:
        raise HTTPException(status_code=409, detail="This obligation has already been cleared")
    if payload.target_amount > outstanding:
        raise HTTPException(
            status_code=422,
            detail=f"Requested support exceeds the live balance of UGX {outstanding:,.0f}",
        )
    support_case = session.scalar(select(SupportCase).where(SupportCase.referral_id == referral.id))
    if support_case and support_case.status not in {"draft", "changes_requested"}:
        raise HTTPException(
            status_code=409,
            detail="The school is reviewing this case. Wait for a decision before editing it.",
        )
    student = session.get(Student, referral.student_id)
    person = session.get(Person, student.person_id) if student else None
    if student is None or person is None:
        raise HTTPException(status_code=409, detail="Learner identity record is incomplete")
    creating = support_case is None
    if creating:
        support_case = SupportCase(
            school_id=referral.school_id,
            period_id=referral.period_id,
            student_id=referral.student_id,
            referral_id=referral.id,
            guardian_auth_user_id=user.id,
            public_code=f"HS-{uuid.uuid4().hex[:10].upper()}",
            title="",
            public_summary="",
            need_category=payload.need_category,
            target_amount=payload.target_amount,
            created_by=user.email or str(user.id),
        )
        session.add(support_case)
    support_case.requirement_assignment_id = payload.requirement_assignment_id
    support_case.title = payload.title.strip()
    support_case.public_summary = payload.public_summary.strip()
    support_case.private_context = payload.private_context.strip() or None
    support_case.need_category = payload.need_category
    support_case.target_amount = payload.target_amount
    support_case.status = "draft"
    support_case.review_notes = None
    _assert_public_text(support_case, student, person, support_case.title)
    _assert_public_text(support_case, student, person, support_case.public_summary)
    session.flush()
    consent = session.scalar(
        select(SupportConsent).where(SupportConsent.case_id == support_case.id)
    )
    if consent is None:
        consent = SupportConsent(
            case_id=support_case.id,
            school_id=referral.school_id,
            guardian_link_id=referral.guardian_link_id,
            method="guardian_portal",
            scope_version=referral.privacy_notice_version or PRIVACY_NOTICE_VERSION,
            anonymous_publication=True,
            gemma_processing=referral.gemma_processing,
            cross_border_processing=referral.cross_border_processing,
            child_assent_status=referral.child_assent_status,
            recorded_by=user.email or str(user.id),
        )
        session.add(consent)
    session.add(
        AuditEvent(
            school_id=referral.school_id,
            entity_type="support_case",
            entity_id=support_case.id,
            action="guardian_draft_created" if creating else "guardian_draft_updated",
            actor=user.email or str(user.id),
            summary="Guardian saved a private support case draft",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Another active case already covers this learner obligation",
        ) from error
    return _guardian_case_payload(session, support_case)


@router.post("/guardian/referrals/{referral_id}/case/submit")
def submit_guardian_support_case(
    referral_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    support_case = session.scalar(
        select(SupportCase).where(
            SupportCase.referral_id == referral.id,
            SupportCase.guardian_auth_user_id == user.id,
        )
    )
    if support_case is None:
        raise HTTPException(status_code=404, detail="Save a case draft before submitting it")
    if support_case.status not in {"draft", "changes_requested"}:
        raise HTTPException(status_code=409, detail="This case has already been submitted")
    if len(support_case.title.strip()) < 4 or len(support_case.public_summary.strip()) < 20:
        raise HTTPException(status_code=422, detail="Complete the public title and summary")
    if len((support_case.private_context or "").strip()) < 20:
        raise HTTPException(status_code=422, detail="Add enough private context for school review")
    live_limit = _case_live_limit(session, support_case)
    if live_limit <= 0:
        raise HTTPException(status_code=409, detail="This obligation has already been cleared")
    if support_case.target_amount > live_limit:
        support_case.target_amount = live_limit
    support_case.status = "submitted"
    support_case.submitted_at = datetime.now(UTC)
    support_case.review_notes = None
    referral.status = "case_submitted"
    session.add(
        AuditEvent(
            school_id=referral.school_id,
            entity_type="support_case",
            entity_id=support_case.id,
            action="submitted",
            actor=user.email or str(user.id),
            summary="Guardian submitted a private support case for school review",
        )
    )
    _notify_school(
        session,
        support_case,
        "case_submitted",
        "Guardian submitted a support case",
        "A private support case is ready for safeguarding and financial review.",
    )
    session.commit()
    return _guardian_case_payload(session, support_case)


@router.post("/guardian/referrals/{referral_id}/consent")
def decide_referral_consent(
    referral_id: uuid.UUID,
    payload: SupportReferralConsent,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    if referral.status not in {"awaiting_consent", "declined"}:
        raise HTTPException(status_code=409, detail="This consent decision can no longer change")
    now = datetime.now(UTC)
    referral.privacy_notice_version = payload.privacy_notice_version
    referral.guardian_authority_confirmed = payload.guardian_authority_confirmed
    referral.age_verification_method = payload.age_verification_method
    referral.anonymous_publication = payload.anonymous_publication
    referral.gemma_processing = payload.gemma_processing
    referral.cross_border_processing = payload.cross_border_processing
    referral.child_assent_status = payload.child_assent_status
    referral.child_assent_reason = (payload.child_assent_reason or "").strip() or None
    referral.consented_by_user_id = user.id
    referral.consented_at = now
    referral.withdrawn_at = None
    referral.status = "consented" if payload.action == "grant" else "declined"
    session.add(
        AuditEvent(
            school_id=referral.school_id,
            entity_type="support_referral",
            entity_id=referral.id,
            action=referral.status,
            actor=user.email or str(user.id),
            summary=f"Guardian {referral.status} private support participation",
        )
    )
    emit_support_notification(
        session,
        school_id=referral.school_id,
        recipient_type="school",
        event_type=f"consent_{referral.status}",
        title=f"Guardian {referral.status} support participation",
        body="The guardian's scoped consent decision is available in the Support workspace.",
        href="/support-admin",
        related_type="support_referral",
        related_id=referral.id,
        dedup_key=f"referral:{referral.id}:consent:{referral.status}:school",
    )
    session.commit()
    return _referral_payload(session, referral)


@router.post("/guardian/referrals/{referral_id}/withdraw")
def withdraw_referral_consent(
    referral_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    if referral.status == "withdrawn":
        return _referral_payload(session, referral)
    referral.status = "withdrawn"
    referral.withdrawn_at = datetime.now(UTC)
    referral.anonymous_publication = False
    referral.gemma_processing = False
    referral.cross_border_processing = False
    open_cases = session.scalars(
        select(SupportCase).where(
            SupportCase.student_id == referral.student_id,
            SupportCase.period_id == referral.period_id,
            SupportCase.status.in_(
                (
                    "draft",
                    "changes_requested",
                    "submitted",
                    "review",
                    "approved",
                    "published",
                )
            ),
        )
    ).all()
    for support_case in open_cases:
        support_case.status = "withdrawn"
    session.add(
        AuditEvent(
            school_id=referral.school_id,
            entity_type="support_referral",
            entity_id=referral.id,
            action="withdrawn",
            actor=user.email or str(user.id),
            summary="Guardian withdrew support participation consent",
        )
    )
    session.commit()
    return _referral_payload(session, referral)


@router.get("/public/campaigns")
def list_public_campaigns(session: Session = Depends(get_session)):
    cases = session.scalars(
        select(SupportCase)
        .where(SupportCase.status.in_(("published", "funded", "closed")))
        .order_by(SupportCase.published_at.desc())
    ).all()
    changed = False
    for item in cases:
        before = (item.target_amount, item.status)
        _refresh_case_target(session, item, "system:live-obligation-check")
        changed = changed or before != (item.target_amount, item.status)
    if changed:
        session.commit()
    return [_public_payload(session, item, detail=False) for item in cases]


@router.get("/public/campaigns/{public_code}")
def get_public_campaign(public_code: str, session: Session = Depends(get_session)):
    support_case = _public_campaign(session, public_code)
    before = (support_case.target_amount, support_case.status)
    _refresh_case_target(session, support_case, "system:live-obligation-check")
    if before != (support_case.target_amount, support_case.status):
        session.commit()
    return _public_payload(session, support_case, detail=True)


@router.post("/public/campaigns/{public_code}/pledges", status_code=status.HTTP_201_CREATED)
def create_public_pledge(
    public_code: str,
    payload: SupportPledgeCreate,
    session: Session = Depends(get_session),
):
    return _pledge_payload(
        _create_pledge(
            session,
            public_code=public_code,
            payload=payload,
            donor_user_id=None,
        )
    )


@router.post("/donor/campaigns/{public_code}/pledges", status_code=status.HTTP_201_CREATED)
def create_authenticated_donor_pledge(
    public_code: str,
    payload: SupportPledgeCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    donor = session.get(DonorProfile, user.id)
    if donor is None:
        raise HTTPException(status_code=403, detail="Activate your donor workspace first")
    return _pledge_payload(
        _create_pledge(
            session,
            public_code=public_code,
            payload=payload,
            donor_user_id=user.id,
        )
    )


@router.get("/public/campaigns/{public_code}/pledges/{public_reference}")
def track_public_pledge(
    public_code: str,
    public_reference: str,
    session: Session = Depends(get_session),
):
    support_case = _public_campaign(session, public_code)
    pledge = session.scalar(
        select(SupportPledge).where(
            SupportPledge.case_id == support_case.id,
            SupportPledge.public_reference == public_reference.upper(),
        )
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Contribution reference not found")
    payment = session.get(Payment, pledge.payment_id) if pledge.payment_id else None
    return {
        "public_reference": pledge.public_reference,
        "campaign_code": support_case.public_code,
        "amount": pledge.amount,
        "currency": pledge.currency,
        "status": pledge.status,
        "created_at": pledge.created_at,
        "verified_at": pledge.verified_at,
        "rejection_reason": pledge.rejection_reason,
        "reversal_reason": pledge.reversal_reason,
        "allocation": (
            {
                "status": "posted_to_verified_learner_obligation",
                "receipt_no": payment.receipt_no,
            }
            if payment
            else None
        ),
    }


@router.get("/public/campaigns/{public_code}/pledges/{public_reference}/receipt")
def get_public_pledge_receipt(
    public_code: str,
    public_reference: str,
    session: Session = Depends(get_session),
):
    support_case = _public_campaign(session, public_code)
    pledge = session.scalar(
        select(SupportPledge).where(
            SupportPledge.case_id == support_case.id,
            SupportPledge.public_reference == public_reference.upper(),
            SupportPledge.status.in_(("verified", "reversed")),
        )
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Verified contribution receipt not found")
    return _receipt_payload(session, pledge, include_settlement_reference=False)


@router.get("/donor/contributions")
def list_donor_contributions(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if session.get(DonorProfile, user.id) is None:
        raise HTTPException(status_code=403, detail="Activate your donor workspace first")
    rows = session.scalars(
        select(SupportPledge)
        .where(SupportPledge.donor_auth_user_id == user.id)
        .order_by(SupportPledge.created_at.desc())
    ).all()
    result = []
    for item in rows:
        support_case = session.get(SupportCase, item.case_id)
        outcomes = session.scalars(
            select(SupportAttestation)
            .where(
                SupportAttestation.case_id == item.case_id,
                SupportAttestation.status == "approved",
                SupportAttestation.is_public.is_(True),
            )
            .order_by(SupportAttestation.reviewed_at)
        ).all()
        timeline = [
            {
                "type": "pledged",
                "title": "Contribution recorded",
                "detail": "Awaiting independent confirmation in the school account.",
                "occurred_at": item.created_at,
            }
        ]
        if item.verified_at:
            timeline.append(
                {
                    "type": "verified",
                    "title": "Received and allocated by the school",
                    "detail": "An official privacy-safe receipt is available.",
                    "occurred_at": item.verified_at,
                }
            )
        timeline.extend(
            {
                "type": f"outcome_{outcome.attestation_type}",
                "title": "Outcome evidence approved",
                "detail": outcome.redacted_statement,
                "occurred_at": outcome.reviewed_at,
            }
            for outcome in outcomes
        )
        result.append(
            {
                **_pledge_payload(item),
                "id": item.id,
                "campaign_code": support_case.public_code,
                "created_at": item.created_at,
                "verified_at": item.verified_at,
                "receipt_available": item.status in {"verified", "reversed"},
                "timeline": timeline,
            }
        )
    return result


@router.get("/donor/contributions/{pledge_id}/receipt")
def get_donor_receipt(
    pledge_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    pledge = session.scalar(
        select(SupportPledge).where(
            SupportPledge.id == pledge_id,
            SupportPledge.donor_auth_user_id == user.id,
            SupportPledge.status.in_(("verified", "reversed")),
        )
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return _receipt_payload(session, pledge, include_settlement_reference=True)


@router.get("/payment-destinations")
def list_payment_destinations(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    context.assert_school(school_id)
    return session.scalars(
        select(SupportPaymentDestination)
        .where(SupportPaymentDestination.school_id == context.school_id)
        .order_by(SupportPaymentDestination.created_at.desc())
    ).all()


@router.post("/payment-destinations", status_code=status.HTTP_201_CREATED)
def create_payment_destination(
    payload: SupportPaymentDestinationCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:approve")),
):
    context.assert_school(payload.school_id)
    school = session.get(School, context.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Institution not found")
    if payload.account_name.strip().casefold() != school.name.strip().casefold():
        raise HTTPException(
            status_code=422,
            detail=f"The account name must exactly match the institution name: {school.name}",
        )
    destination = SupportPaymentDestination(
        school_id=context.school_id,
        channel=payload.channel,
        label=payload.label.strip(),
        provider_name=payload.provider_name.strip(),
        account_name=school.name,
        account_reference=payload.account_reference.strip(),
        instructions=payload.instructions.strip(),
        created_by=context.actor,
    )
    session.add(destination)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_payment_destination",
            entity_id=destination.id,
            action="created",
            actor=context.actor,
            summary=f"Created pending {destination.channel} support destination",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This payment destination already exists"
        ) from error
    session.refresh(destination)
    return destination


@router.post("/payment-destinations/{destination_id}/decision")
def decide_payment_destination(
    destination_id: uuid.UUID,
    payload: SupportPaymentDestinationDecision,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:approve")),
):
    destination = session.scalar(
        select(SupportPaymentDestination).where(
            SupportPaymentDestination.id == destination_id,
            SupportPaymentDestination.school_id == context.school_id,
        )
    )
    if destination is None:
        raise HTTPException(status_code=404, detail="Payment destination not found")
    destination.verification_status = "verified" if payload.action == "verify" else "disabled"
    destination.verified_by = context.actor if payload.action == "verify" else None
    destination.verified_at = datetime.now(UTC) if payload.action == "verify" else None
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_payment_destination",
            entity_id=destination.id,
            action=destination.verification_status,
            actor=context.actor,
            summary=f"Marked {destination.label} {destination.verification_status}",
        )
    )
    session.commit()
    return destination


@router.get("/cases")
def list_support_cases(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    context.assert_school(school_id)
    rows = session.execute(
        select(SupportCase, Student, Person)
        .join(Student, Student.id == SupportCase.student_id)
        .join(Person, Person.id == Student.person_id)
        .where(SupportCase.school_id == school_id)
        .order_by(SupportCase.created_at.desc())
    ).all()
    result = []
    changed = False
    for item, student, person in rows:
        before = (item.target_amount, item.status)
        _refresh_case_target(session, item, context.actor)
        changed = changed or before != (item.target_amount, item.status)
        result.append(
            {
                "id": item.id,
                "public_code": item.public_code,
                "student_id": student.id,
                "student_name": f"{person.first_name} {person.last_name}",
                "admission_no": student.admission_no,
                "title": item.title,
                "need_category": item.need_category,
                "target_amount": item.target_amount,
                "verified_amount": _money_total(session, item.id, "verified"),
                "pending_amount": _money_total(session, item.id, "pending"),
                "currency": item.currency,
                "risk_level": item.risk_level,
                "status": item.status,
                "has_consent": _active_consent(session, item.id) is not None,
                "has_ai_review": _latest_review(session, item.id) is not None,
                "guardian_authored": item.guardian_auth_user_id is not None,
                "review_notes": item.review_notes,
                "created_at": item.created_at,
            }
        )
    if changed:
        session.commit()
    return result


@router.get("/eligibility")
def support_case_eligibility(
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
) -> dict:
    context.assert_school(school_id)
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=period_id,
    )
    student = session.scalar(
        select(Student).where(
            Student.id == student_id,
            Student.school_id == context.school_id,
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    outstanding = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.school_id == context.school_id,
            LedgerEntry.period_id == period.id,
            LedgerEntry.student_id == student.id,
        )
    ) or Decimal("0")
    outstanding = max(outstanding, Decimal("0"))
    return {
        "student_id": student.id,
        "period_id": period.id,
        "general_outstanding": outstanding,
        "eligible": outstanding > 0,
    }


@router.get("/cases/{case_id}")
def get_support_case(
    case_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    support_case = _private_case(session, case_id, context.school_id)
    student = session.get(Student, support_case.student_id)
    person = session.get(Person, student.person_id) if student else None
    if student is None or person is None:
        raise HTTPException(status_code=409, detail="Learner record is incomplete")
    before = (support_case.target_amount, support_case.status)
    _refresh_case_target(session, support_case, context.actor)
    if before != (support_case.target_amount, support_case.status):
        session.commit()
    guardian_rows = session.execute(
        select(GuardianLink, Person)
        .join(Person, Person.id == GuardianLink.person_id)
        .where(GuardianLink.student_id == student.id)
        .order_by(GuardianLink.is_primary.desc(), Person.first_name)
    ).all()
    consent = _active_consent(session, case_id)
    review = _latest_review(session, case_id)
    return {
        "id": support_case.id,
        "public_code": support_case.public_code,
        "student": {
            "id": student.id,
            "name": f"{person.first_name} {person.last_name}",
            "admission_no": student.admission_no,
        },
        "title": support_case.title,
        "public_summary": support_case.public_summary,
        "private_context": (
            support_case.private_context if context.role in {"owner", "bursar"} else None
        ),
        "need_category": support_case.need_category,
        "target_amount": support_case.target_amount,
        "verified_amount": _money_total(session, case_id, "verified"),
        "pending_amount": _money_total(session, case_id, "pending"),
        "currency": support_case.currency,
        "risk_level": support_case.risk_level,
        "risk_reasons": json.loads(support_case.risk_reasons),
        "status": support_case.status,
        "guardian_authored": support_case.guardian_auth_user_id is not None,
        "review_notes": support_case.review_notes,
        "submitted_at": support_case.submitted_at,
        "reviewed_at": support_case.reviewed_at,
        "guardians": [
            {
                "id": guardian.id,
                "name": f"{guardian_person.first_name} {guardian_person.last_name}",
                "relationship": guardian.relationship,
                "is_primary": guardian.is_primary,
            }
            for guardian, guardian_person in guardian_rows
        ],
        "consent": (
            {
                "method": consent.method,
                "gemma_processing": consent.gemma_processing,
                "cross_border_processing": consent.cross_border_processing,
                "child_assent_status": consent.child_assent_status,
                "recorded_at": consent.recorded_at,
            }
            if consent
            else None
        ),
        "ai_review": json.loads(review.result_json) if review else None,
    }


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def create_support_case(
    payload: SupportCaseCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    context.assert_school(payload.school_id)
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        writable=True,
    )
    student = session.scalar(
        select(Student).where(
            Student.id == payload.student_id, Student.school_id == context.school_id
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    person = session.get(Person, student.person_id)
    if person is None:
        raise HTTPException(status_code=409, detail="Learner identity record is incomplete")
    assignment = None
    if payload.requirement_assignment_id:
        assignment = session.scalar(
            select(StudentRequirement).where(
                StudentRequirement.id == payload.requirement_assignment_id,
                StudentRequirement.student_id == student.id,
            )
        )
        if assignment is None:
            raise HTTPException(status_code=422, detail="Requirement does not belong to learner")
        paid = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.requirement_assignment_id == assignment.id
            )
        ) or Decimal("0")
        outstanding = max(assignment.expected_amount - paid, Decimal("0"))
    else:
        outstanding = session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.school_id == context.school_id,
                LedgerEntry.period_id == period.id,
                LedgerEntry.student_id == student.id,
            )
        ) or Decimal("0")
        outstanding = max(outstanding, Decimal("0"))
    if outstanding <= 0:
        raise HTTPException(
            status_code=409, detail="Learner has no verified outstanding obligation"
        )
    if payload.target_amount > outstanding:
        raise HTTPException(
            status_code=422,
            detail=f"Campaign target exceeds the verified balance of UGX {outstanding:,.0f}",
        )
    duplicate_filters = [
        SupportCase.student_id == student.id,
        SupportCase.period_id == period.id,
        SupportCase.status.notin_(("closed", "withdrawn")),
    ]
    if assignment:
        duplicate_filters.append(SupportCase.requirement_assignment_id == assignment.id)
    else:
        duplicate_filters.append(SupportCase.requirement_assignment_id.is_(None))
    if session.scalar(select(SupportCase.id).where(*duplicate_filters)):
        raise HTTPException(
            status_code=409, detail="An active campaign already covers this obligation"
        )
    placeholder = SupportCase(
        school_id=context.school_id,
        period_id=period.id,
        student_id=student.id,
        requirement_assignment_id=assignment.id if assignment else None,
        public_code=f"HS-{uuid.uuid4().hex[:10].upper()}",
        title=payload.title.strip(),
        public_summary=payload.public_summary.strip(),
        need_category=payload.need_category,
        target_amount=payload.target_amount,
        risk_level="high" if datetime.now(UTC).date() > period.due_date else "review",
        risk_reasons=json.dumps(
            [
                f"UGX {outstanding:,.0f} remains outstanding in the selected period",
                (
                    f"The school due date passed on {period.due_date.isoformat()}"
                    if datetime.now(UTC).date() > period.due_date
                    else f"The school due date is {period.due_date.isoformat()}"
                ),
            ]
        ),
        created_by=context.actor,
    )
    _assert_public_text(placeholder, student, person, placeholder.title)
    _assert_public_text(placeholder, student, person, placeholder.public_summary)
    session.add(placeholder)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_case",
            entity_id=placeholder.id,
            action="created",
            actor=context.actor,
            summary=f"Created anonymous support case {placeholder.public_code}",
        )
    )
    session.commit()
    return {"id": placeholder.id, "public_code": placeholder.public_code, "status": "draft"}


@router.post("/cases/{case_id}/consent")
def record_support_consent(
    case_id: uuid.UUID,
    payload: SupportConsentCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    support_case = _private_case(session, case_id, context.school_id)
    if support_case.status not in {"draft", "review"}:
        raise HTTPException(status_code=409, detail="Consent cannot change after publication")
    if not payload.anonymous_publication:
        raise HTTPException(
            status_code=422, detail="Harambee Support only permits anonymous campaigns"
        )
    guardian = session.scalar(
        select(GuardianLink).where(
            GuardianLink.id == payload.guardian_link_id,
            GuardianLink.student_id == support_case.student_id,
        )
    )
    if guardian is None:
        raise HTTPException(status_code=422, detail="Guardian does not belong to this learner")
    consent = session.scalar(select(SupportConsent).where(SupportConsent.case_id == case_id))
    if consent is None:
        consent = SupportConsent(
            case_id=case_id,
            school_id=context.school_id,
            guardian_link_id=guardian.id,
            recorded_by=context.actor,
        )
        session.add(consent)
    consent.guardian_link_id = guardian.id
    consent.method = payload.method
    consent.scope_version = payload.scope_version
    consent.anonymous_publication = True
    consent.gemma_processing = payload.gemma_processing
    consent.cross_border_processing = payload.cross_border_processing
    consent.child_assent_status = payload.child_assent_status
    consent.status = "active"
    consent.withdrawn_at = None
    support_case.status = "review"
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_consent",
            entity_id=consent.id,
            action="recorded",
            actor=context.actor,
            summary=f"Recorded scoped guardian consent for {support_case.public_code}",
        )
    )
    session.commit()
    return {"status": consent.status, "child_assent_status": consent.child_assent_status}


@router.post("/cases/{case_id}/ai-review")
def review_support_case(
    case_id: uuid.UUID,
    payload: SupportAiReviewCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    support_case = _private_case(session, case_id, context.school_id)
    consent = _active_consent(session, case_id)
    if consent is None or not consent.gemma_processing or not consent.cross_border_processing:
        raise HTTPException(
            status_code=409,
            detail="Guardian consent for Gemma and cross-border processing is required",
        )
    facts = {
        "campaign_code": support_case.public_code,
        "need_category": support_case.need_category,
        "target_amount": str(support_case.target_amount),
        "currency": support_case.currency,
        "rule_based_risk": support_case.risk_level,
        "rule_based_reasons": json.loads(support_case.risk_reasons),
        "draft_public_summary": support_case.public_summary,
    }
    input_material = (
        json.dumps(facts, sort_keys=True)
        + hashlib.sha256((payload.evidence_image_base64 or "").encode()).hexdigest()
    )
    usage = start_assistant_usage(
        session,
        user_id=context.user.id,
        persona="school",
        task="case_review",
        school_id=context.school_id,
        scope_id=support_case.id,
    )
    try:
        model_name, result = _call_gemma(
            case_payload=facts,
            evidence_image_base64=payload.evidence_image_base64,
            evidence_mime_type=payload.evidence_mime_type,
        )
    except HTTPException:
        finish_assistant_usage(session, usage, "failed")
        session.commit()
        raise
    student = session.get(Student, support_case.student_id)
    person = session.get(Person, student.person_id) if student else None
    if student is None or person is None:
        raise HTTPException(status_code=409, detail="Learner record is incomplete")
    safe_summary = str(result["safe_public_summary"]).strip()
    _assert_public_text(support_case, student, person, safe_summary)
    support_case.public_summary = safe_summary
    support_case.risk_level = result["risk_level"]
    review = SupportAiReview(
        case_id=support_case.id,
        school_id=context.school_id,
        model_name=model_name,
        input_hash=hashlib.sha256(input_material.encode()).hexdigest(),
        result_json=json.dumps(result),
        created_by=context.actor,
    )
    session.add(review)
    finish_assistant_usage(session, usage, "completed")
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_ai_review",
            entity_id=review.id,
            action="created",
            actor=context.actor,
            summary=f"Gemma reviewed anonymous support case {support_case.public_code}",
        )
    )
    session.commit()
    return {"id": review.id, "model": model_name, **result}


@router.post("/cases/{case_id}/review-decision")
def decide_support_case_review(
    case_id: uuid.UUID,
    payload: SupportCaseReviewDecision,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    support_case = _private_case(session, case_id, context.school_id)
    if support_case.guardian_auth_user_id is None:
        raise HTTPException(status_code=409, detail="This is a legacy school-authored case")
    if support_case.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted cases can be reviewed")
    referral = session.get(SupportReferral, support_case.referral_id)
    if referral is None or referral.status != "case_submitted":
        raise HTTPException(status_code=409, detail="The guardian referral is not active")
    live_limit = _refresh_case_target(session, support_case, context.actor)
    if live_limit <= 0 or support_case.status == "closed":
        session.commit()
        raise HTTPException(status_code=409, detail="The learner obligation has been cleared")
    if payload.action == "approve":
        if context.role != "owner":
            raise HTTPException(
                status_code=403,
                detail="Only an institution owner can approve a support case",
            )
        if referral.gemma_processing and _latest_review(session, case_id) is None:
            raise HTTPException(
                status_code=409,
                detail="Complete the consented Gemma review before owner approval",
            )
        support_case.status = "approved"
        support_case.approved_by = context.actor
        support_case.review_notes = (payload.note or "").strip() or None
        action = "approved"
        summary = "Owner approved guardian-authored support case for publication"
    else:
        support_case.status = "changes_requested"
        support_case.review_notes = (payload.note or "").strip()
        support_case.approved_by = None
        referral.status = "consented"
        action = "changes_requested"
        summary = "School requested changes to guardian-authored support case"
    support_case.reviewed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_case",
            entity_id=support_case.id,
            action=action,
            actor=context.actor,
            summary=summary,
        )
    )
    _notify_guardian(
        session,
        support_case,
        action,
        "Support case approved" if action == "approved" else "The school requested changes",
        (
            "An institution owner approved the anonymous case for publication."
            if action == "approved"
            else support_case.review_notes or "Review the school's note and resubmit the case."
        ),
    )
    session.commit()
    return {"id": support_case.id, "status": support_case.status}


@router.post("/cases/{case_id}/publish")
def publish_support_case(
    case_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:approve")),
):
    support_case = _private_case(session, case_id, context.school_id)
    if support_case.status in {"published", "funded", "closed"}:
        return {"public_code": support_case.public_code, "status": support_case.status}
    if support_case.guardian_auth_user_id is not None and support_case.status != "approved":
        raise HTTPException(status_code=409, detail="Owner approval is required before publication")
    live_limit = _refresh_case_target(session, support_case, context.actor)
    if live_limit <= 0 or support_case.status == "closed":
        session.commit()
        raise HTTPException(status_code=409, detail="The learner obligation has been cleared")
    consent = _active_consent(session, case_id)
    if consent is None or not consent.anonymous_publication:
        raise HTTPException(
            status_code=409, detail="Active anonymous publication consent is required"
        )
    if consent.child_assent_status == "declined":
        raise HTTPException(status_code=409, detail="The learner declined publication")
    referral = session.scalar(
        select(SupportReferral).where(
            SupportReferral.student_id == support_case.student_id,
            SupportReferral.period_id == support_case.period_id,
        )
    )
    if referral and (
        referral.status not in {"consented", "case_submitted"}
        or not referral.anonymous_publication
        or referral.child_assent_status == "declined"
    ):
        raise HTTPException(
            status_code=409,
            detail="Active guardian portal consent and an acceptable learner view are required",
        )
    if consent.gemma_processing and _latest_review(session, case_id) is None:
        raise HTTPException(status_code=409, detail="Complete the Gemma review before publication")
    support_case.status = "published"
    support_case.approved_by = support_case.approved_by or context.actor
    support_case.published_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_case",
            entity_id=support_case.id,
            action="published",
            actor=context.actor,
            summary=f"Published anonymous support campaign {support_case.public_code}",
        )
    )
    _notify_guardian(
        session,
        support_case,
        "campaign_published",
        "The anonymous campaign is now public",
        "Donors can now support the verified school obligation without seeing learner identity.",
    )
    session.commit()
    return {"public_code": support_case.public_code, "status": support_case.status}


@router.get("/cases/{case_id}/pledges")
def list_case_pledges(
    case_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    _private_case(session, case_id, context.school_id)
    rows = session.scalars(
        select(SupportPledge)
        .where(SupportPledge.case_id == case_id)
        .order_by(SupportPledge.created_at.desc())
    ).all()
    return [
        {
            "id": item.id,
            "public_reference": item.public_reference,
            "external_reference": item.external_reference,
            "donor_display_name": item.donor_display_name or "Anonymous donor",
            "amount": item.amount,
            "currency": item.currency,
            "status": item.status,
            "created_at": item.created_at,
            "verified_at": item.verified_at,
            "rejection_reason": item.rejection_reason,
            "reversal_reason": item.reversal_reason,
        }
        for item in rows
    ]


@router.post("/pledges/{pledge_id}/verify")
def verify_support_pledge(
    pledge_id: uuid.UUID,
    payload: SupportPledgeVerify,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:settle")),
):
    pledge = session.scalar(
        select(SupportPledge)
        .where(SupportPledge.id == pledge_id, SupportPledge.school_id == context.school_id)
        .with_for_update()
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    if pledge.status != "pending":
        raise HTTPException(status_code=409, detail="Contribution has already been decided")
    support_case = session.scalar(
        select(SupportCase).where(SupportCase.id == pledge.case_id).with_for_update()
    )
    if support_case is None:
        raise HTTPException(status_code=404, detail="Support case not found")
    if payload.action == "reject":
        pledge.status = "rejected"
        pledge.rejection_reason = payload.reason.strip() if payload.reason else None
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="support_pledge",
                entity_id=pledge.id,
                action="rejected",
                actor=context.actor,
                summary=f"Rejected {pledge.public_reference}: {payload.reason}",
            )
        )
        _notify_guardian(
            session,
            support_case,
            "pledge_rejected",
            "A pending contribution was not confirmed",
            "The school rejected an unmatched settlement; verified campaign totals did not change.",
            suffix=f":{pledge.id}",
        )
        if pledge.donor_auth_user_id:
            emit_support_notification(
                session,
                school_id=support_case.school_id,
                recipient_type="donor",
                recipient_auth_user_id=pledge.donor_auth_user_id,
                event_type="pledge_rejected",
                title="The school could not verify your contribution",
                body=pledge.rejection_reason
                or "Contact the school with your settlement reference.",
                href="/donor",
                related_type="support_pledge",
                related_id=pledge.id,
                dedup_key=f"pledge:{pledge.id}:rejected:donor",
            )
        session.commit()
        return {"public_reference": pledge.public_reference, "status": pledge.status}
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=support_case.period_id,
        writable=True,
    )
    verified_before = _money_total(session, support_case.id, "verified")
    if verified_before + pledge.amount > support_case.target_amount:
        raise HTTPException(status_code=409, detail="Verification would overfund the campaign")
    student = session.get(Student, support_case.student_id)
    if student is None or student.school_id != context.school_id:
        raise HTTPException(status_code=404, detail="Learner not found")
    if support_case.requirement_assignment_id:
        assignment = session.get(StudentRequirement, support_case.requirement_assignment_id)
        if assignment is None:
            raise HTTPException(status_code=409, detail="Covered requirement no longer exists")
        already_paid = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.requirement_assignment_id == assignment.id
            )
        ) or Decimal("0")
        live_outstanding = max(assignment.expected_amount - already_paid, Decimal("0"))
    else:
        live_outstanding = session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.school_id == context.school_id,
                LedgerEntry.period_id == period.id,
                LedgerEntry.student_id == student.id,
            )
        ) or Decimal("0")
        live_outstanding = max(live_outstanding, Decimal("0"))
    if pledge.amount > live_outstanding:
        raise HTTPException(
            status_code=409,
            detail="Contribution exceeds the learner's current verified obligation",
        )
    destination = (
        session.get(SupportPaymentDestination, pledge.payment_destination_id)
        if pledge.payment_destination_id
        else None
    )
    if destination is None or destination.verification_status != "verified":
        raise HTTPException(
            status_code=409,
            detail="The school payment destination is no longer verified",
        )
    payment_id = uuid.uuid4()
    financial_reference = (
        "HSP-"
        + hashlib.sha256(f"{support_case.id}:{pledge.external_reference}".encode())
        .hexdigest()[:24]
        .upper()
    )
    payment = Payment(
        id=payment_id,
        school_id=context.school_id,
        period_id=period.id,
        receipt_no=_next_support_receipt(session, context.school_id),
        external_reference=financial_reference,
        payer_name=pledge.donor_display_name or "Anonymous donor",
        note=f"Verified support contribution {pledge.public_reference}",
        channel=destination.channel,
        amount=pledge.amount,
        transaction_type="receipt",
        created_by=context.actor,
    )
    session.add(payment)
    session.flush()
    allocation = PaymentAllocation(
        id=uuid.uuid4(),
        payment_id=payment.id,
        student_id=student.id,
        requirement_assignment_id=support_case.requirement_assignment_id,
        allocation_type=(
            "requirement" if support_case.requirement_assignment_id else "fees"
        ),
        amount=pledge.amount,
    )
    ledger = LedgerEntry(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=period.id,
        student_id=student.id,
        entry_type="payment",
        amount=-pledge.amount,
        reference=financial_reference,
        description=f"Anonymous learner support {support_case.public_code}",
        payment_id=payment.id,
    )
    commitment = hashlib.sha256(
        f"{payment.id}|{pledge.amount}|{pledge.currency}|{financial_reference}".encode()
    ).hexdigest()
    anchor = StellarAnchor(
        id=uuid.uuid4(),
        payment_id=payment.id,
        commitment_hash=commitment,
        status="pending",
    )
    pledge.status = "verified"
    pledge.payment_id = payment.id
    pledge.verified_at = datetime.now(UTC)
    pledge.verified_by = context.actor
    if verified_before + pledge.amount == support_case.target_amount:
        support_case.status = "funded"
    session.add_all([allocation, ledger, anchor])
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_pledge",
            entity_id=pledge.id,
            action="verified",
            actor=context.actor,
            summary=f"Verified and allocated {pledge.public_reference}",
        )
    )
    _notify_guardian(
        session,
        support_case,
        "pledge_verified",
        "The school verified a contribution",
        f"UGX {pledge.amount:,.0f} was posted to the verified learner obligation.",
        suffix=f":{pledge.id}",
    )
    _notify_school(
        session,
        support_case,
        "receipt_issued",
        "Official support receipt issued",
        f"Receipt {payment.receipt_no} records the verified allocation.",
        suffix=f":{pledge.id}",
    )
    if pledge.donor_auth_user_id:
        emit_support_notification(
            session,
            school_id=support_case.school_id,
            recipient_type="donor",
            recipient_auth_user_id=pledge.donor_auth_user_id,
            event_type="pledge_verified",
            title="Your contribution reached the school account",
            body=f"Receipt {payment.receipt_no} confirms UGX {pledge.amount:,.0f} was allocated.",
            href=f"/donor/receipts/{pledge.id}",
            related_type="support_pledge",
            related_id=pledge.id,
            dedup_key=f"pledge:{pledge.id}:verified:donor",
        )
    if support_case.status == "funded":
        _notify_guardian(
            session,
            support_case,
            "campaign_funded",
            "The campaign target is complete",
            "The school has verified enough support to cover the campaign target.",
        )
        _notify_school(
            session,
            support_case,
            "campaign_funded",
            "Campaign target completed",
            "Add fulfilment or enrolment evidence for human review.",
        )
        _notify_case_donors(
            session,
            support_case,
            "campaign_funded",
            "The campaign target is complete",
            "Verified school receipts now cover the anonymous campaign target.",
        )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Contribution could not be posted twice"
        ) from error
    return {
        "public_reference": pledge.public_reference,
        "status": pledge.status,
        "receipt_no": payment.receipt_no,
        "campaign_status": support_case.status,
    }


@router.post("/pledges/{pledge_id}/reverse")
def reverse_support_pledge(
    pledge_id: uuid.UUID,
    payload: SupportPledgeReverse,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:approve")),
):
    pledge = session.scalar(
        select(SupportPledge)
        .where(SupportPledge.id == pledge_id, SupportPledge.school_id == context.school_id)
        .with_for_update()
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    if pledge.status != "verified" or pledge.payment_id is None:
        raise HTTPException(status_code=409, detail="Only a verified contribution can be reversed")
    support_case = session.scalar(
        select(SupportCase).where(SupportCase.id == pledge.case_id).with_for_update()
    )
    original = session.get(Payment, pledge.payment_id)
    if support_case is None or original is None:
        raise HTTPException(status_code=409, detail="Posted contribution record is incomplete")
    reversal_id = uuid.uuid4()
    reversal_reference = f"REV-{hashlib.sha256(str(original.id).encode()).hexdigest()[:24].upper()}"
    reversal = Payment(
        id=reversal_id,
        school_id=context.school_id,
        period_id=original.period_id,
        receipt_no=_next_support_receipt(session, context.school_id),
        external_reference=reversal_reference,
        payer_name=original.payer_name,
        note=f"Reversal of {original.receipt_no}: {payload.reason.strip()}",
        channel=original.channel,
        amount=-pledge.amount,
        currency=pledge.currency,
        status="reconciled",
        transaction_type="reversal",
        original_payment_id=original.id,
        correction_reason=payload.reason.strip(),
        created_by=context.actor,
    )
    session.add(reversal)
    session.flush()
    session.add_all(
        [
            PaymentAllocation(
                id=uuid.uuid4(),
                payment_id=reversal.id,
                student_id=support_case.student_id,
                requirement_assignment_id=support_case.requirement_assignment_id,
                allocation_type=(
                    "requirement" if support_case.requirement_assignment_id else "fees"
                ),
                amount=-pledge.amount,
            ),
            LedgerEntry(
                id=uuid.uuid4(),
                school_id=context.school_id,
                period_id=original.period_id,
                student_id=support_case.student_id,
                entry_type="reversal",
                amount=pledge.amount,
                reference=reversal_reference,
                description=f"Support contribution reversal {support_case.public_code}",
                payment_id=reversal.id,
            ),
        ]
    )
    original.status = "reversed"
    pledge.status = "reversed"
    pledge.reversed_at = datetime.now(UTC)
    pledge.reversed_by = context.actor
    pledge.reversal_reason = payload.reason.strip()
    pledge.reversal_payment_id = reversal.id
    if support_case.status == "funded":
        support_case.status = "published"
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_pledge",
            entity_id=pledge.id,
            action="reversed",
            actor=context.actor,
            summary=f"Reversed {pledge.public_reference}: {payload.reason.strip()}",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Contribution reversal could not be posted"
        ) from error
    return {
        "public_reference": pledge.public_reference,
        "status": pledge.status,
        "reversal_receipt_no": reversal.receipt_no,
        "campaign_status": support_case.status,
    }


@router.post("/pledges/{pledge_id}/receipt/reissue")
def reissue_support_receipt(
    pledge_id: uuid.UUID,
    payload: SupportReceiptReissueCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    pledge = session.scalar(
        select(SupportPledge).where(
            SupportPledge.id == pledge_id,
            SupportPledge.school_id == context.school_id,
            SupportPledge.status.in_(("verified", "reversed")),
        )
    )
    if pledge is None:
        raise HTTPException(status_code=404, detail="Posted contribution not found")
    event = SupportReceiptReissue(
        school_id=context.school_id,
        pledge_id=pledge.id,
        reason=payload.reason.strip(),
        reissued_by=context.actor,
    )
    session.add(event)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_receipt_reissue",
            entity_id=event.id,
            action="created",
            actor=context.actor,
            summary=f"Reissued receipt for {pledge.public_reference}",
        )
    )
    session.commit()
    return _receipt_payload(session, pledge, include_settlement_reference=True)


@router.post("/cases/{case_id}/attestations", status_code=status.HTTP_201_CREATED)
def create_support_attestation(
    case_id: uuid.UUID,
    payload: SupportAttestationCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:write")),
):
    support_case = _private_case(session, case_id, context.school_id)
    if support_case.status not in {"published", "funded", "closed"}:
        raise HTTPException(status_code=409, detail="Publish the campaign before adding proof")
    if payload.attestation_type == "enrolment" and not payload.attendance_band:
        raise HTTPException(
            status_code=422, detail="Attendance band is required for enrolment proof"
        )
    student = session.get(Student, support_case.student_id)
    person = session.get(Person, student.person_id) if student else None
    if student is None or person is None:
        raise HTTPException(status_code=409, detail="Learner record is incomplete")
    attestation = SupportAttestation(
        case_id=support_case.id,
        school_id=context.school_id,
        attestation_type=payload.attestation_type,
        statement=payload.statement.strip(),
        attendance_band=payload.attendance_band,
        evidence_hash=payload.evidence_hash.lower() if payload.evidence_hash else None,
        status="submitted",
        is_public=False,
        submitted_by_role="school",
        submitted_by=context.actor,
    )
    session.add(attestation)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_attestation",
            entity_id=attestation.id,
            action="submitted",
            actor=context.actor,
            summary=f"Submitted {payload.attestation_type} evidence for human review",
        )
    )
    _notify_school(
        session,
        support_case,
        "outcome_submitted",
        "Outcome evidence is ready for review",
        "Approve a redacted statement before donors can see this update.",
        suffix=f":{attestation.id}",
    )
    session.commit()
    return {"id": attestation.id, "status": attestation.status}


@router.post(
    "/guardian/referrals/{referral_id}/acknowledgements",
    status_code=status.HTTP_201_CREATED,
)
def create_guardian_acknowledgement(
    referral_id: uuid.UUID,
    payload: GuardianAcknowledgementCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    referral = _guardian_referral(session, referral_id, user.id)
    support_case = session.scalar(select(SupportCase).where(SupportCase.referral_id == referral.id))
    if support_case is None or support_case.status not in {"funded", "closed"}:
        raise HTTPException(
            status_code=409,
            detail="Guardian acknowledgement is available after the campaign is funded",
        )
    attestation = SupportAttestation(
        case_id=support_case.id,
        school_id=support_case.school_id,
        attestation_type="guardian_acknowledgement",
        statement=payload.statement.strip(),
        attendance_band=payload.attendance_band,
        status="submitted",
        is_public=False,
        submitted_by_user_id=user.id,
        submitted_by_role="guardian",
        submitted_by=user.email or str(user.id),
    )
    session.add(attestation)
    session.flush()
    session.add(
        AuditEvent(
            school_id=support_case.school_id,
            entity_type="support_attestation",
            entity_id=attestation.id,
            action="guardian_submitted",
            actor=user.email or str(user.id),
            summary="Guardian submitted private outcome acknowledgement for review",
        )
    )
    _notify_school(
        session,
        support_case,
        "outcome_submitted",
        "Guardian outcome acknowledgement needs review",
        "Review and redact the acknowledgement before any public or donor update.",
        suffix=f":{attestation.id}",
    )
    session.commit()
    return {"id": attestation.id, "status": attestation.status}


@router.get("/cases/{case_id}/attestations")
def list_support_attestations(
    case_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    _private_case(session, case_id, context.school_id)
    rows = session.scalars(
        select(SupportAttestation)
        .where(
            SupportAttestation.case_id == case_id,
            SupportAttestation.school_id == context.school_id,
        )
        .order_by(SupportAttestation.submitted_at.desc())
    ).all()
    return [
        {
            "id": item.id,
            "type": item.attestation_type,
            "statement": item.statement,
            "redacted_statement": item.redacted_statement,
            "attendance_band": item.attendance_band,
            "evidence_hash": item.evidence_hash,
            "status": item.status,
            "submitted_by_role": item.submitted_by_role,
            "submitted_at": item.submitted_at,
            "reviewed_at": item.reviewed_at,
            "rejection_reason": item.rejection_reason,
        }
        for item in rows
    ]


@router.get("/attestations")
def list_school_support_attestations(
    school_id: uuid.UUID,
    status_filter: str | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:read")),
):
    context.assert_school(school_id)
    query = (
        select(SupportAttestation, SupportCase)
        .join(SupportCase, SupportCase.id == SupportAttestation.case_id)
        .where(SupportAttestation.school_id == context.school_id)
    )
    if status_filter:
        if status_filter not in {"submitted", "approved", "rejected"}:
            raise HTTPException(status_code=422, detail="Invalid outcome evidence status")
        query = query.where(SupportAttestation.status == status_filter)
    rows = session.execute(query.order_by(SupportAttestation.submitted_at.desc())).all()
    return [
        {
            "id": item.id,
            "campaign_code": support_case.public_code,
            "campaign_title": support_case.title,
            "type": item.attestation_type,
            "statement": item.statement,
            "redacted_statement": item.redacted_statement,
            "attendance_band": item.attendance_band,
            "evidence_hash": item.evidence_hash,
            "status": item.status,
            "submitted_by_role": item.submitted_by_role,
            "submitted_at": item.submitted_at,
            "reviewed_at": item.reviewed_at,
            "rejection_reason": item.rejection_reason,
        }
        for item, support_case in rows
    ]


@router.post("/attestations/{attestation_id}/review")
def review_support_attestation(
    attestation_id: uuid.UUID,
    payload: SupportAttestationReview,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("support:approve")),
):
    attestation = session.scalar(
        select(SupportAttestation)
        .where(
            SupportAttestation.id == attestation_id,
            SupportAttestation.school_id == context.school_id,
        )
        .with_for_update()
    )
    if attestation is None:
        raise HTTPException(status_code=404, detail="Outcome evidence not found")
    if attestation.status != "submitted":
        raise HTTPException(status_code=409, detail="Outcome evidence has already been reviewed")
    support_case = _private_case(session, attestation.case_id, context.school_id)
    if payload.action == "approve":
        student = session.get(Student, support_case.student_id)
        person = session.get(Person, student.person_id) if student else None
        if student is None or person is None:
            raise HTTPException(status_code=409, detail="Learner record is incomplete")
        redacted = payload.redacted_statement.strip()
        _assert_public_text(support_case, student, person, redacted)
        attestation.status = "approved"
        attestation.redacted_statement = redacted
        attestation.is_public = True
        attestation.rejection_reason = None
        event = "outcome_approved"
    else:
        attestation.status = "rejected"
        attestation.is_public = False
        attestation.rejection_reason = payload.reason.strip()
        event = "outcome_rejected"
    attestation.reviewed_by = context.actor
    attestation.reviewed_at = datetime.now(UTC)
    attestation.verified_by = context.actor
    attestation.verified_at = attestation.reviewed_at
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="support_attestation",
            entity_id=attestation.id,
            action=event,
            actor=context.actor,
            summary=f"Human review {attestation.status} outcome evidence",
        )
    )
    _notify_guardian(
        session,
        support_case,
        event,
        "Outcome update approved"
        if attestation.status == "approved"
        else "Outcome update needs revision",
        redacted if attestation.status == "approved" else attestation.rejection_reason,
        suffix=f":{attestation.id}",
    )
    if attestation.status == "approved":
        _notify_case_donors(
            session,
            support_case,
            event,
            "A verified campaign outcome is available",
            redacted,
            suffix=f":{attestation.id}",
        )
    session.commit()
    return {"id": attestation.id, "status": attestation.status}
