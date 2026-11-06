import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.financial_reporting import (
    FinancialTotals,
    aggregate_financial_totals,
    load_learner_financial_totals,
)
from harambeeone_api.models import (
    AcademicPeriod,
    AuditEvent,
    BalanceCarryForward,
    LedgerEntry,
    PeriodClose,
    PeriodCloseLearner,
    PeriodReopening,
    PeriodReopeningCorrection,
    PeriodReopeningLearner,
)
from harambeeone_api.schemas import PeriodReopeningCreate

router = APIRouter(prefix="/api/v1", tags=["controlled reopening"])
ReopeningReadContext = Annotated[SchoolContext, Depends(require_permission("periods:read"))]
ReopeningWriteContext = Annotated[SchoolContext, Depends(require_permission("periods:reopen"))]
ZERO = Decimal("0")
FINANCIAL_FIELDS = (
    "opening_balance",
    "charges",
    "credits",
    "payments",
    "refunds",
    "reversals",
    "assessment_adjustments",
    "net_assessed",
    "net_collected",
    "period_activity",
    "closing_balance",
    "outstanding",
    "credit_balance",
)


def _financial_values(totals: FinancialTotals) -> dict[str, Decimal]:
    return {field: Decimal(getattr(totals, field)) for field in FINANCIAL_FIELDS}


def _row_values(row: PeriodCloseLearner | PeriodReopeningLearner) -> dict[str, Decimal]:
    return {field: Decimal(getattr(row, field)) for field in FINANCIAL_FIELDS}


def _apply_delta(totals: FinancialTotals, correction_type: str, amount: Decimal) -> FinancialTotals:
    values = {
        field: Decimal(getattr(totals, field)) for field in FinancialTotals.__dataclass_fields__
    }
    if correction_type == "charge":
        values["charges"] += amount
    else:
        values["credits"] += amount
    values["net_assessed"] = (
        values["charges"] - values["credits"] + values["assessment_adjustments"]
    )
    values["period_activity"] = values["net_assessed"] - values["net_collected"]
    values["closing_balance"] = values["opening_balance"] + values["period_activity"]
    return FinancialTotals(**values)


def _load_original_close(
    session: Session, school_id: uuid.UUID, period_id: uuid.UUID
) -> PeriodClose:
    close = session.scalar(
        select(PeriodClose)
        .where(PeriodClose.school_id == school_id, PeriodClose.period_id == period_id)
        .options(selectinload(PeriodClose.learners))
    )
    if close is None:
        raise HTTPException(status_code=409, detail="This period has no immutable closing snapshot")
    return close


def _load_latest_reopening(
    session: Session, school_id: uuid.UUID, period_id: uuid.UUID
) -> PeriodReopening | None:
    return session.scalar(
        select(PeriodReopening)
        .where(PeriodReopening.school_id == school_id, PeriodReopening.period_id == period_id)
        .options(
            selectinload(PeriodReopening.corrections),
            selectinload(PeriodReopening.learners),
        )
        .order_by(PeriodReopening.snapshot_version.desc())
        .limit(1)
    )


def _period(session: Session, school_id: uuid.UUID, period_id: uuid.UUID, *, lock: bool = False):
    statement = (
        select(AcademicPeriod)
        .where(AcademicPeriod.id == period_id, AcademicPeriod.school_id == school_id)
        .options(joinedload(AcademicPeriod.academic_year))
    )
    if lock:
        statement = statement.with_for_update()
    period = session.scalar(statement)
    if period is None:
        raise HTTPException(status_code=404, detail="Academic period not found")
    return period


def _reopening_payload(session: Session, reopening: PeriodReopening) -> dict:
    period = _period(session, reopening.school_id, reopening.period_id)
    destination = (
        _period(session, reopening.school_id, reopening.destination_period_id)
        if reopening.destination_period_id
        else None
    )
    return {
        "id": reopening.id,
        "period_id": reopening.period_id,
        "period_name": period.name,
        "academic_year_name": period.academic_year.name,
        "snapshot_version": reopening.snapshot_version,
        "original_snapshot_hash": reopening.original_snapshot_hash,
        "prior_snapshot_hash": reopening.prior_snapshot_hash,
        "revised_snapshot_hash": reopening.revised_snapshot_hash,
        "reason": reopening.reason,
        "correction_count": reopening.correction_count,
        "learner_count": reopening.learner_count,
        "net_adjustment": reopening.net_adjustment,
        **{field: getattr(reopening, field) for field in FINANCIAL_FIELDS},
        "destination_period": (
            {
                "id": destination.id,
                "name": destination.name,
                "academic_year_name": destination.academic_year.name,
            }
            if destination
            else None
        ),
        "applied_by": reopening.applied_by,
        "applied_at": reopening.applied_at,
        "corrections": [
            {
                "id": item.id,
                "student_id": item.student_id,
                "admission_no": item.admission_no,
                "learner_name": item.learner_name,
                "correction_type": item.correction_type,
                "amount": item.amount,
                "reason": item.reason,
                "reference": item.reference,
                "propagated": item.destination_period_id is not None,
            }
            for item in reopening.corrections
        ],
    }


def _baseline_rows(
    close: PeriodClose, latest: PeriodReopening | None
) -> list[PeriodCloseLearner | PeriodReopeningLearner]:
    return list(latest.learners if latest else close.learners)


def _assert_live_history_matches(
    session: Session,
    period: AcademicPeriod,
    rows: list[PeriodCloseLearner | PeriodReopeningLearner],
) -> dict[uuid.UUID, FinancialTotals]:
    live = load_learner_financial_totals(session, period=period)
    sealed_student_ids = {row.student_id for row in rows}
    if set(live) - sealed_student_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                "Closed history contains learner activity outside its sealed evidence. "
                "Resolve the integrity difference before reopening."
            ),
        )
    for row in rows:
        totals = live.get(row.student_id, FinancialTotals())
        if _financial_values(totals) != _row_values(row):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Closed history no longer matches its latest sealed evidence. "
                    "Resolve the integrity difference before reopening."
                ),
            )
    return {row.student_id: live.get(row.student_id, FinancialTotals()) for row in rows}


@router.get("/academic-periods/{period_id}/reopening-preview")
def reopening_preview(
    period_id: uuid.UUID,
    context: ReopeningReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    period = _period(session, context.school_id, period_id)
    if period.status != "closed":
        raise HTTPException(status_code=409, detail="Only a closed period can be reviewed")
    close = _load_original_close(session, context.school_id, period.id)
    latest = _load_latest_reopening(session, context.school_id, period.id)
    rows = _baseline_rows(close, latest)
    carry = session.scalar(
        select(BalanceCarryForward).where(
            BalanceCarryForward.school_id == context.school_id,
            BalanceCarryForward.source_period_id == period.id,
        )
    )
    destination = (
        _period(session, context.school_id, carry.destination_period_id) if carry else None
    )
    blockers = []
    if destination and destination.status == "closed":
        blockers.append(
            "The carried destination is already closed. "
            "Correct the most recent closed period first."
        )
    _assert_live_history_matches(session, period, rows)
    return {
        "period": {
            "id": period.id,
            "name": period.name,
            "academic_year_name": period.academic_year.name,
        },
        "original_snapshot_hash": close.snapshot_hash,
        "effective_snapshot_hash": latest.revised_snapshot_hash if latest else close.snapshot_hash,
        "next_snapshot_version": (latest.snapshot_version if latest else 1) + 1,
        "reopening_count": (latest.snapshot_version - 1) if latest else 0,
        "destination_period": (
            {
                "id": destination.id,
                "name": destination.name,
                "academic_year_name": destination.academic_year.name,
                "status": destination.status,
            }
            if destination
            else None
        ),
        "can_apply": not blockers,
        "blockers": blockers,
        "learners": [
            {
                "student_id": row.student_id,
                "admission_no": row.admission_no,
                "learner_name": row.learner_name,
                "class_name": row.class_name,
                "stream_name": row.stream_name,
                "closing_balance": row.closing_balance,
            }
            for row in rows
        ],
    }


@router.get("/academic-periods/{period_id}/reopenings")
def reopening_history(
    period_id: uuid.UUID,
    context: ReopeningReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> list[dict]:
    _period(session, context.school_id, period_id)
    rows = session.scalars(
        select(PeriodReopening)
        .where(
            PeriodReopening.school_id == context.school_id, PeriodReopening.period_id == period_id
        )
        .options(selectinload(PeriodReopening.corrections))
        .order_by(PeriodReopening.snapshot_version.desc())
    ).all()
    return [_reopening_payload(session, row) for row in rows]


@router.post(
    "/academic-periods/{period_id}/controlled-reopening",
    status_code=status.HTTP_201_CREATED,
)
def apply_controlled_reopening(
    period_id: uuid.UUID,
    payload: PeriodReopeningCreate,
    response: Response,
    context: ReopeningWriteContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    existing = session.scalar(
        select(PeriodReopening)
        .where(
            PeriodReopening.school_id == context.school_id,
            PeriodReopening.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(PeriodReopening.corrections))
    )
    if existing is not None:
        if existing.period_id != period_id:
            raise HTTPException(status_code=409, detail="That retry key belongs to another period")
        response.status_code = status.HTTP_200_OK
        return {**_reopening_payload(session, existing), "idempotent_replay": True}

    period = _period(session, context.school_id, period_id, lock=True)
    if period.status != "closed":
        raise HTTPException(status_code=409, detail="Only a closed period can be reopened")
    close = _load_original_close(session, context.school_id, period.id)
    latest = _load_latest_reopening(session, context.school_id, period.id)
    rows = _baseline_rows(close, latest)
    live = _assert_live_history_matches(session, period, rows)
    rows_by_student = {row.student_id: row for row in rows}
    requested_ids = {item.student_id for item in payload.corrections}
    if requested_ids - rows_by_student.keys():
        raise HTTPException(
            status_code=422,
            detail="Every corrected learner must exist in the sealed closing evidence",
        )
    carry = session.scalar(
        select(BalanceCarryForward).where(
            BalanceCarryForward.school_id == context.school_id,
            BalanceCarryForward.source_period_id == period.id,
        )
    )
    destination = (
        _period(session, context.school_id, carry.destination_period_id, lock=True)
        if carry
        else None
    )
    if destination and destination.status == "closed":
        raise HTTPException(
            status_code=409,
            detail=(
                "The carried destination is already closed. "
                "Correct the most recent closed period first."
            ),
        )

    corrected = dict(live)
    signed_corrections: list[tuple[object, Decimal]] = []
    for item in payload.corrections:
        signed = item.amount if item.correction_type == "charge" else -item.amount
        corrected[item.student_id] = _apply_delta(
            corrected[item.student_id], item.correction_type, item.amount
        )
        signed_corrections.append((item, signed))
    totals = aggregate_financial_totals(corrected.values())
    version = (latest.snapshot_version if latest else 1) + 1
    prior_hash = latest.revised_snapshot_hash if latest else close.snapshot_hash
    net_adjustment = sum((amount for _item, amount in signed_corrections), ZERO)
    learner_document = [
        {
            "student_id": str(row.student_id),
            "admission_no": row.admission_no,
            "class_name": row.class_name,
            **{
                key: str(value)
                for key, value in _financial_values(corrected[row.student_id]).items()
            },
        }
        for row in sorted(rows, key=lambda value: value.admission_no)
    ]
    hash_document = {
        "version": version,
        "school_id": str(context.school_id),
        "period_id": str(period.id),
        "original_snapshot_hash": close.snapshot_hash,
        "prior_snapshot_hash": prior_hash,
        "reason": payload.reason,
        "corrections": [
            {
                "student_id": str(item.student_id),
                "type": item.correction_type,
                "amount": str(amount),
                "reason": item.reason,
            }
            for item, amount in sorted(
                signed_corrections, key=lambda value: str(value[0].student_id)
            )
        ],
        "learners": learner_document,
    }
    revised_hash = hashlib.sha256(
        json.dumps(hash_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    reopening = PeriodReopening(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=period.id,
        original_close_id=close.id,
        previous_reopening_id=latest.id if latest else None,
        destination_period_id=destination.id if destination else None,
        idempotency_key=payload.idempotency_key,
        reason=payload.reason,
        snapshot_version=version,
        original_snapshot_hash=close.snapshot_hash,
        prior_snapshot_hash=prior_hash,
        revised_snapshot_hash=revised_hash,
        correction_count=len(payload.corrections),
        learner_count=len(rows),
        net_adjustment=net_adjustment,
        controls_json=json.dumps(
            {
                "original_controls": json.loads(close.controls_json),
                "correction_count": len(payload.corrections),
                "destination_propagated": destination is not None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        applied_by=context.actor,
        applied_at=datetime.now(UTC),
        **_financial_values(totals),
    )
    reopening.learners = [
        PeriodReopeningLearner(
            id=uuid.uuid4(),
            school_id=context.school_id,
            period_id=period.id,
            student_id=row.student_id,
            class_id=row.class_id,
            stream_id=row.stream_id,
            admission_no=row.admission_no,
            learner_name=row.learner_name,
            class_name=row.class_name,
            stream_name=row.stream_name,
            **_financial_values(corrected[row.student_id]),
        )
        for row in rows
    ]
    corrections = []
    for item, signed in signed_corrections:
        row = rows_by_student[item.student_id]
        correction = PeriodReopeningCorrection(
            id=uuid.uuid4(),
            school_id=context.school_id,
            period_id=period.id,
            destination_period_id=destination.id if destination else None,
            student_id=item.student_id,
            correction_type=item.correction_type,
            amount=signed,
            admission_no=row.admission_no,
            learner_name=row.learner_name,
            reason=item.reason,
            reference=f"REOPEN:{reopening.id.hex[:16]}:{item.student_id.hex[:16]}",
        )
        corrections.append(correction)
    reopening.corrections = corrections
    session.add(reopening)
    session.flush()
    for correction in corrections:
        session.add(
            LedgerEntry(
                school_id=context.school_id,
                period_id=period.id,
                student_id=correction.student_id,
                entry_type=(
                    "period_correction_charge"
                    if correction.correction_type == "charge"
                    else "period_correction_credit"
                ),
                amount=correction.amount,
                currency="UGX",
                reference=correction.reference,
                description=correction.reason,
                reopening_correction_id=correction.id,
            )
        )
        if destination:
            session.add(
                LedgerEntry(
                    school_id=context.school_id,
                    period_id=destination.id,
                    student_id=correction.student_id,
                    entry_type="carry_correction",
                    amount=correction.amount,
                    currency="UGX",
                    reference=f"{correction.reference}:CF",
                    description=f"Controlled correction from {period.name}: {correction.reason}",
                    reopening_correction_id=correction.id,
                )
            )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="period_reopening",
            entity_id=reopening.id,
            action="sealed",
            actor=context.actor,
            summary=(
                f"Applied {reopening.correction_count} controlled correction(s) to {period.name}; "
                f"sealed snapshot version {version}"
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        existing = session.scalar(
            select(PeriodReopening)
            .where(
                PeriodReopening.school_id == context.school_id,
                PeriodReopening.idempotency_key == payload.idempotency_key,
            )
            .options(selectinload(PeriodReopening.corrections))
        )
        if existing is not None and existing.period_id == period_id:
            response.status_code = status.HTTP_200_OK
            return {**_reopening_payload(session, existing), "idempotent_replay": True}
        raise HTTPException(
            status_code=409,
            detail="The period changed while the controlled reopening was being applied",
        ) from error
    session.refresh(reopening)
    return {**_reopening_payload(session, reopening), "idempotent_replay": False}
