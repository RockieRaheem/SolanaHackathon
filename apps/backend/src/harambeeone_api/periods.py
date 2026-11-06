import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, or_, select, union_all
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
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    AuditEvent,
    BalanceCarryForward,
    BalanceCarryForwardLine,
    BillingAdjustment,
    BillingPublication,
    CashierBatchPayment,
    CashierCollectionBatch,
    Enrollment,
    FeeStructure,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    PeriodClose,
    PeriodCloseLearner,
    Person,
    Requirement,
    School,
    SchoolProgramme,
    StatementTransaction,
    Stream,
    Student,
)
from harambeeone_api.schemas import (
    AcademicPeriodTransition,
    AcademicPeriodUpdate,
    AcademicYearCreate,
    BalanceCarryForwardCreate,
)

router = APIRouter(prefix="/api/v1", tags=["academic periods"])
PeriodReadContext = Annotated[SchoolContext, Depends(require_permission("periods:read"))]
PeriodManageContext = Annotated[SchoolContext, Depends(require_permission("periods:manage"))]
ZERO = Decimal("0")


def _activity_count(session: Session, period_id: uuid.UUID) -> int:
    models = (
        Enrollment,
        FeeStructure,
        Requirement,
        BillingAdjustment,
        BillingPublication,
        LedgerEntry,
        Payment,
    )
    return sum(
        session.scalar(select(func.count()).select_from(model).where(model.period_id == period_id))
        or 0
        for model in models
    )


def _activity_counts(session: Session, period_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Count all period activity in one database round trip."""
    if not period_ids:
        return {}
    models = (
        Enrollment,
        FeeStructure,
        Requirement,
        BillingAdjustment,
        BillingPublication,
        LedgerEntry,
        Payment,
    )
    activity = union_all(
        *(
            select(
                model.period_id.label("period_id"),
                func.count().label("activity_count"),
            )
            .where(model.period_id.in_(period_ids))
            .group_by(model.period_id)
            for model in models
        )
    ).subquery()
    return {
        period_id: int(count)
        for period_id, count in session.execute(
            select(activity.c.period_id, func.sum(activity.c.activity_count)).group_by(
                activity.c.period_id
            )
        )
    }


def _period_payload(period: AcademicPeriod, *, activity_count: int | None = None) -> dict:
    return {
        "id": period.id,
        "academic_year_id": period.academic_year_id,
        "academic_year": period.academic_year.year,
        "academic_year_name": period.academic_year.name,
        "name": period.name,
        "sequence": period.sequence,
        "opening_date": period.opening_date,
        "closing_date": period.closing_date,
        "due_date": period.due_date,
        "status": period.status,
        "is_operational": period.status in {"open", "closing"},
        "activity_count": activity_count,
    }


def resolve_period(
    session: Session,
    *,
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    academic_year: int | None = None,
    term: int | None = None,
    writable: bool = False,
) -> AcademicPeriod:
    statement = (
        select(AcademicPeriod)
        .join(AcademicYear, AcademicYear.id == AcademicPeriod.academic_year_id)
        .where(AcademicPeriod.school_id == school_id)
        .options(joinedload(AcademicPeriod.academic_year))
    )
    if period_id is not None:
        statement = statement.where(AcademicPeriod.id == period_id)
    elif academic_year is not None and term is not None:
        statement = statement.where(
            AcademicYear.year == academic_year, AcademicPeriod.sequence == term
        )
    else:
        statement = statement.where(AcademicPeriod.status.in_(("open", "closing")))
    period = session.scalar(statement)
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select or open an academic period before continuing",
        )
    if writable and period.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This academic period is closed and cannot be changed",
        )
    return period


def _refresh_year_status(year: AcademicYear) -> None:
    statuses = {period.status for period in year.periods}
    if "open" in statuses:
        year.status = "open"
    elif "closing" in statuses:
        year.status = "closing"
    elif statuses and statuses == {"closed"}:
        year.status = "closed"
    else:
        year.status = "draft"


def _control(
    code: str,
    title: str,
    status: str,
    detail: str,
    action_href: str,
    *,
    count: int = 0,
    amount: Decimal = ZERO,
) -> dict:
    return {
        "code": code,
        "title": title,
        "status": status,
        "detail": detail,
        "count": count,
        "amount": amount,
        "action_href": action_href,
    }


def _close_readiness(session: Session, period: AcademicPeriod) -> dict:
    unresolved_count, unresolved_amount = session.execute(
        select(
            func.count(StatementTransaction.id),
            func.coalesce(func.sum(StatementTransaction.amount), 0),
        ).where(
            StatementTransaction.school_id == period.school_id,
            StatementTransaction.period_id == period.id,
            StatementTransaction.status.in_(("suggested", "unmatched", "unidentified")),
        )
    ).one()
    reconciled_source, reconciled_posted = session.execute(
        select(
            func.coalesce(func.sum(StatementTransaction.amount), 0),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .select_from(StatementTransaction)
        .outerjoin(Payment, Payment.id == StatementTransaction.payment_id)
        .where(
            StatementTransaction.school_id == period.school_id,
            StatementTransaction.period_id == period.id,
            StatementTransaction.status == "reconciled",
        )
    ).one()
    reconciliation_variance = Decimal(reconciled_source) - Decimal(reconciled_posted)

    pending_batches, pending_expected = session.execute(
        select(
            func.count(CashierCollectionBatch.id),
            func.coalesce(func.sum(CashierCollectionBatch.expected_cash), 0),
        ).where(
            CashierCollectionBatch.school_id == period.school_id,
            CashierCollectionBatch.period_id == period.id,
            CashierCollectionBatch.status != "signed_off",
        )
    ).one()
    unbatched_count, unbatched_amount = session.execute(
        select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
        .select_from(Payment)
        .outerjoin(CashierBatchPayment, CashierBatchPayment.payment_id == Payment.id)
        .where(
            Payment.school_id == period.school_id,
            Payment.period_id == period.id,
            Payment.channel == "cash",
            Payment.transaction_type == "receipt",
            CashierBatchPayment.id.is_(None),
        )
    ).one()
    allocation_rows = session.execute(
        select(
            Payment.id,
            Payment.amount,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .outerjoin(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .where(Payment.school_id == period.school_id, Payment.period_id == period.id)
        .group_by(Payment.id, Payment.amount)
    ).all()
    allocation_differences = [
        Decimal(payment_amount) - Decimal(allocated_amount)
        for _payment_id, payment_amount, allocated_amount in allocation_rows
        if Decimal(payment_amount) != Decimal(allocated_amount)
    ]
    unallocated_rows = session.execute(
        select(
            PaymentAllocation.student_id,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(
            Payment.school_id == period.school_id,
            Payment.period_id == period.id,
            PaymentAllocation.allocation_type == "unallocated",
        )
        .group_by(PaymentAllocation.student_id)
    ).all()
    positive_unallocated = [
        Decimal(amount) for _student_id, amount in unallocated_rows if amount > 0
    ]
    explained_batches = session.scalars(
        select(CashierCollectionBatch).where(
            CashierCollectionBatch.school_id == period.school_id,
            CashierCollectionBatch.period_id == period.id,
            CashierCollectionBatch.status == "signed_off",
            (CashierCollectionBatch.variance != 0)
            | (CashierCollectionBatch.deposit_amount != CashierCollectionBatch.counted_cash),
        )
    ).all()
    explained_difference = sum(
        (
            abs(batch.variance) + abs(batch.deposit_amount - batch.counted_cash)
            for batch in explained_batches
        ),
        ZERO,
    )

    controls = [
        _control(
            "reconciliation_items",
            "Statement review",
            "blocked" if unresolved_count else "passed",
            (
                "Resolve suggested, unmatched, and unidentified provider transactions."
                if unresolved_count
                else "Every imported transaction is reconciled, rejected, or formally reversed."
            ),
            "/reconciliation",
            count=unresolved_count,
            amount=Decimal(unresolved_amount),
        ),
        _control(
            "reconciliation_variance",
            "Reconciliation balance",
            "blocked" if reconciliation_variance else "passed",
            (
                "Reconciled provider value must equal the linked posted receipts."
                if reconciliation_variance
                else "Reconciled provider value agrees with linked posted receipts."
            ),
            "/reports",
            amount=reconciliation_variance,
        ),
        _control(
            "cash_up_batches",
            "Cash-up approval",
            "blocked" if pending_batches else "passed",
            (
                "Submit or resolve every open, returned, or awaiting-approval cash-up."
                if pending_batches
                else "Every created cash-up batch has supervisor sign-off."
            ),
            "/reconciliation",
            count=pending_batches,
            amount=Decimal(pending_expected),
        ),
        _control(
            "unbatched_cash",
            "Cash receipt coverage",
            "blocked" if unbatched_count else "passed",
            (
                "Include every cash receipt in a cashier batch before closing."
                if unbatched_count
                else "Every cash receipt is represented in a cashier batch."
            ),
            "/reconciliation",
            count=unbatched_count,
            amount=Decimal(unbatched_amount),
        ),
        _control(
            "payment_allocation_balance",
            "Payment allocation balance",
            "blocked" if allocation_differences else "passed",
            (
                "Correct receipts whose amount does not equal their learner allocations."
                if allocation_differences
                else "Every receipt and correction agrees with its learner allocations."
            ),
            "/payments",
            count=len(allocation_differences),
            amount=sum((abs(item) for item in allocation_differences), ZERO),
        ),
        _control(
            "unallocated_credit",
            "Unallocated learner credit",
            "blocked" if positive_unallocated else "passed",
            (
                "Allocate positive learner credit to a fee or requirement before closing."
                if positive_unallocated
                else "No positive unallocated learner credit remains."
            ),
            "/payments",
            count=len(positive_unallocated),
            amount=sum(positive_unallocated, ZERO),
        ),
        _control(
            "approved_variances",
            "Approved cash differences",
            "warning" if explained_batches else "passed",
            (
                "Supervisor-approved explained differences remain in the permanent audit record."
                if explained_batches
                else "No signed-off cash or deposit differences require disclosure."
            ),
            "/reports",
            count=len(explained_batches),
            amount=explained_difference,
        ),
    ]
    blockers = [item for item in controls if item["status"] == "blocked"]
    warnings = [item for item in controls if item["status"] == "warning"]
    return {
        "period": _period_payload(period, activity_count=_activity_count(session, period.id)),
        "ready_to_close": not blockers,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "controls": controls,
    }


def _financial_values(totals: FinancialTotals) -> dict[str, Decimal]:
    return {
        "opening_balance": totals.opening_balance,
        "charges": totals.charges,
        "credits": totals.credits,
        "payments": totals.payments,
        "refunds": totals.refunds,
        "reversals": totals.reversals,
        "assessment_adjustments": totals.assessment_adjustments,
        "net_assessed": totals.net_assessed,
        "net_collected": totals.net_collected,
        "period_activity": totals.period_activity,
        "closing_balance": totals.closing_balance,
        "outstanding": totals.outstanding,
        "credit_balance": totals.credit_balance,
    }


def _period_close_payload(close: PeriodClose, *, include_learners: bool = False) -> dict:
    payload = {
        "id": close.id,
        "school_id": close.school_id,
        "period_id": close.period_id,
        "snapshot_version": close.snapshot_version,
        "snapshot_hash": close.snapshot_hash,
        "learner_count": close.learner_count,
        "warning_count": close.warning_count,
        **_financial_values(close),
        "controls": json.loads(close.controls_json),
        "closed_by": close.closed_by,
        "closed_at": close.closed_at,
    }
    if include_learners:
        payload["learners"] = [
            {
                "student_id": item.student_id,
                "admission_no": item.admission_no,
                "learner_name": item.learner_name,
                "class_id": item.class_id,
                "class_name": item.class_name,
                "stream_id": item.stream_id,
                "stream_name": item.stream_name,
                **_financial_values(item),
            }
            for item in close.learners
        ]
    return payload


def _next_configured_period(session: Session, source: AcademicPeriod) -> AcademicPeriod | None:
    return session.scalar(
        select(AcademicPeriod)
        .join(AcademicYear, AcademicYear.id == AcademicPeriod.academic_year_id)
        .where(
            AcademicPeriod.school_id == source.school_id,
            or_(
                AcademicYear.year > source.academic_year.year,
                and_(
                    AcademicYear.year == source.academic_year.year,
                    AcademicPeriod.sequence > source.sequence,
                ),
            ),
        )
        .options(joinedload(AcademicPeriod.academic_year))
        .order_by(AcademicYear.year, AcademicPeriod.sequence)
        .limit(1)
    )


def _load_balance_carry(
    session: Session,
    *,
    school_id: uuid.UUID,
    source_period_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> BalanceCarryForward | None:
    statement = (
        select(BalanceCarryForward)
        .where(BalanceCarryForward.school_id == school_id)
        .options(selectinload(BalanceCarryForward.lines))
    )
    if source_period_id is not None:
        statement = statement.where(BalanceCarryForward.source_period_id == source_period_id)
    if idempotency_key is not None:
        statement = statement.where(BalanceCarryForward.idempotency_key == idempotency_key)
    return session.scalar(statement)


def _balance_carry_payload(
    session: Session,
    carry: BalanceCarryForward,
    *,
    include_lines: bool = False,
) -> dict:
    periods = {
        period.id: period
        for period in session.scalars(
            select(AcademicPeriod)
            .where(
                AcademicPeriod.id.in_(
                    (carry.source_period_id, carry.destination_period_id)
                )
            )
            .options(joinedload(AcademicPeriod.academic_year))
        ).all()
    }
    source = periods[carry.source_period_id]
    destination = periods[carry.destination_period_id]
    payload = {
        "id": carry.id,
        "school_id": carry.school_id,
        "source_close_id": carry.source_close_id,
        "source_period_id": carry.source_period_id,
        "source_period_name": source.name,
        "source_academic_year_name": source.academic_year.name,
        "destination_period_id": carry.destination_period_id,
        "destination_period_name": destination.name,
        "destination_academic_year_name": destination.academic_year.name,
        "destination_status": destination.status,
        "source_snapshot_hash": carry.source_snapshot_hash,
        "learner_count": carry.learner_count,
        "debt_total": carry.debt_total,
        "credit_total": carry.credit_total,
        "net_balance": carry.net_balance,
        "posted_by": carry.posted_by,
        "posted_at": carry.posted_at,
    }
    if include_lines:
        payload["lines"] = [
            {
                "student_id": line.student_id,
                "admission_no": line.admission_no,
                "learner_name": line.learner_name,
                "amount": line.amount,
                "balance_type": "debt" if line.amount > ZERO else "credit",
                "ledger_entry_id": line.ledger_entry_id,
            }
            for line in carry.lines
        ]
    return payload


def _carry_forward_preview(
    session: Session,
    *,
    school_id: uuid.UUID,
    source_period_id: uuid.UUID,
    destination_period_id: uuid.UUID,
) -> tuple[AcademicPeriod, AcademicPeriod, PeriodClose, list[PeriodCloseLearner], dict]:
    source = resolve_period(session, school_id=school_id, period_id=source_period_id)
    if source.status != "closed":
        raise HTTPException(
            status_code=409,
            detail="Close the source period before carrying balances",
        )
    close = session.scalar(
        select(PeriodClose)
        .where(
            PeriodClose.school_id == school_id,
            PeriodClose.period_id == source.id,
        )
        .options(selectinload(PeriodClose.learners))
    )
    if close is None:
        raise HTTPException(
            status_code=409,
            detail="This closed period has no controlled closing snapshot",
        )
    destination = resolve_period(
        session,
        school_id=school_id,
        period_id=destination_period_id,
    )
    next_period = _next_configured_period(session, source)
    if next_period is None:
        raise HTTPException(
            status_code=409,
            detail="Create the next academic period before carrying balances",
        )
    if destination.id != next_period.id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Balances must carry into the next configured period: "
                f"{next_period.name} · {next_period.academic_year.name}"
            ),
        )
    if destination.status not in {"draft", "open"}:
        raise HTTPException(
            status_code=409,
            detail="The destination period must be draft or open",
        )
    rows = [row for row in close.learners if row.closing_balance != ZERO]
    student_ids = [row.student_id for row in rows]
    conflicting_openings = (
        session.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.school_id == school_id,
                LedgerEntry.period_id == destination.id,
                LedgerEntry.student_id.in_(student_ids),
                LedgerEntry.entry_type.in_(("opening_balance", "carried_balance")),
            )
        )
        if student_ids
        else 0
    ) or 0
    debt_total = sum((row.closing_balance for row in rows if row.closing_balance > ZERO), ZERO)
    credit_total = sum((-row.closing_balance for row in rows if row.closing_balance < ZERO), ZERO)
    preview = {
        "source_period": _period_payload(source),
        "destination_period": _period_payload(destination),
        "source_close_id": close.id,
        "source_snapshot_hash": close.snapshot_hash,
        "learner_count": len(rows),
        "debt_learner_count": sum(row.closing_balance > ZERO for row in rows),
        "credit_learner_count": sum(row.closing_balance < ZERO for row in rows),
        "debt_total": debt_total,
        "credit_total": credit_total,
        "net_balance": debt_total - credit_total,
        "conflicting_opening_count": conflicting_openings,
        "ready_to_post": conflicting_openings == 0,
    }
    return source, destination, close, rows, preview


def _create_balance_carry(
    session: Session,
    *,
    school_id: uuid.UUID,
    source: AcademicPeriod,
    destination: AcademicPeriod,
    close: PeriodClose,
    rows: list[PeriodCloseLearner],
    idempotency_key: str,
    actor: str,
) -> BalanceCarryForward:
    debt_total = sum((row.closing_balance for row in rows if row.closing_balance > ZERO), ZERO)
    credit_total = sum((-row.closing_balance for row in rows if row.closing_balance < ZERO), ZERO)
    carry = BalanceCarryForward(
        id=uuid.uuid4(),
        school_id=school_id,
        source_close_id=close.id,
        source_period_id=source.id,
        destination_period_id=destination.id,
        idempotency_key=idempotency_key,
        source_snapshot_hash=close.snapshot_hash,
        learner_count=len(rows),
        debt_total=debt_total,
        credit_total=credit_total,
        net_balance=debt_total - credit_total,
        posted_by=actor,
        posted_at=datetime.now(UTC),
    )
    session.add(carry)
    session.flush()
    for row in rows:
        ledger = LedgerEntry(
            id=uuid.uuid4(),
            school_id=school_id,
            period_id=destination.id,
            student_id=row.student_id,
            entry_type="carried_balance",
            amount=row.closing_balance,
            currency="UGX",
            reference=f"CF:{carry.id.hex[:16]}:{row.student_id.hex[:16]}",
            description=(
                f"Balance carried from {source.name} "
                f"(snapshot {close.snapshot_hash[:12]})"
            ),
        )
        session.add(ledger)
        session.flush()
        session.add(
            BalanceCarryForwardLine(
                carry_forward_id=carry.id,
                school_id=school_id,
                source_period_id=source.id,
                destination_period_id=destination.id,
                source_close_learner_id=row.id,
                student_id=row.student_id,
                ledger_entry_id=ledger.id,
                admission_no=row.admission_no,
                learner_name=row.learner_name,
                amount=row.closing_balance,
            )
        )
    session.flush()
    return carry


def _create_period_close(
    session: Session,
    period: AcademicPeriod,
    readiness: dict,
    *,
    actor: str,
) -> PeriodClose:
    totals_by_student = load_learner_financial_totals(session, period=period)
    enrolled_ids = set(
        session.scalars(
            select(Enrollment.student_id).where(Enrollment.period_id == period.id)
        ).all()
    )
    student_ids = set(totals_by_student) | enrolled_ids
    if session.scalar(
        select(SchoolProgramme.id).where(
            SchoolProgramme.school_id == period.school_id,
            SchoolProgramme.programme_code == "day_care",
        )
    ):
        student_ids.update(
            session.scalars(
                select(Student.id).where(
                    Student.school_id == period.school_id,
                    Student.status == "active",
                )
            ).all()
        )
    learner_rows: list[dict] = []
    if student_ids:
        for student, person, enrollment, academic_class, stream in session.execute(
            select(Student, Person, Enrollment, AcademicClass, Stream)
            .join(Person, Person.id == Student.person_id)
            .outerjoin(
                Enrollment,
                (Enrollment.student_id == Student.id) & (Enrollment.period_id == period.id),
            )
            .outerjoin(AcademicClass, AcademicClass.id == Enrollment.class_id)
            .outerjoin(Stream, Stream.id == Enrollment.stream_id)
            .where(Student.school_id == period.school_id, Student.id.in_(student_ids))
            .order_by(Student.admission_no)
        ).all():
            totals = totals_by_student.get(student.id, FinancialTotals())
            learner_rows.append(
                {
                    "student_id": student.id,
                    "class_id": enrollment.class_id if enrollment else None,
                    "stream_id": enrollment.stream_id if enrollment else None,
                    "admission_no": student.admission_no,
                    "learner_name": " ".join(
                        part
                        for part in (person.first_name, person.middle_name, person.last_name)
                        if part
                    ),
                    "class_name": academic_class.name if academic_class else "Unplaced",
                    "stream_name": stream.name if stream else None,
                    **_financial_values(totals),
                }
            )
    school_totals = aggregate_financial_totals(
        totals_by_student.get(item["student_id"], FinancialTotals()) for item in learner_rows
    )
    controls = readiness["controls"]
    controls_json = json.dumps(controls, default=str, sort_keys=True, separators=(",", ":"))
    hash_document = {
        "version": 1,
        "school_id": str(period.school_id),
        "period_id": str(period.id),
        "totals": {key: str(value) for key, value in _financial_values(school_totals).items()},
        "controls": json.loads(controls_json),
        "learners": [
            {
                key: str(value) if isinstance(value, Decimal | uuid.UUID) else value
                for key, value in row.items()
            }
            for row in learner_rows
        ],
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(hash_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    close = PeriodClose(
        school_id=period.school_id,
        period_id=period.id,
        idempotency_key=f"period-close:{period.id}",
        snapshot_version=1,
        snapshot_hash=snapshot_hash,
        learner_count=len(learner_rows),
        warning_count=readiness["warning_count"],
        controls_json=controls_json,
        closed_by=actor,
        closed_at=datetime.now(UTC),
        **_financial_values(school_totals),
    )
    close.learners = [
        PeriodCloseLearner(
            school_id=period.school_id,
            period_id=period.id,
            **row,
        )
        for row in learner_rows
    ]
    session.add(close)
    session.flush()
    return close


@router.get("/academic-period-templates")
def calendar_templates(context: PeriodReadContext) -> dict:
    return {
        "country": "Uganda",
        "school_id": context.school_id,
        "default_period_names": ["Term 1", "Term 2", "Term 3"],
        "note": (
            "Dates are intentionally editable because the Ministry calendar "
            "and school schedules vary."
        ),
    }


@router.get("/academic-periods")
def list_periods(
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
    school_id: uuid.UUID | None = None,
    include_activity: bool = False,
) -> list[dict]:
    if school_id is not None:
        context.assert_school(school_id)
    periods = session.scalars(
        select(AcademicPeriod)
        .where(AcademicPeriod.school_id == context.school_id)
        .join(AcademicYear, AcademicYear.id == AcademicPeriod.academic_year_id)
        .options(joinedload(AcademicPeriod.academic_year))
        .order_by(AcademicYear.year.desc(), AcademicPeriod.sequence)
    ).all()
    counts = (
        _activity_counts(session, [period.id for period in periods]) if include_activity else {}
    )
    closed_snapshot_ids = set(
        session.scalars(
            select(PeriodClose.period_id).where(PeriodClose.school_id == context.school_id)
        ).all()
    )
    carry_rows = session.execute(
        select(
            BalanceCarryForward.id,
            BalanceCarryForward.source_period_id,
            BalanceCarryForward.destination_period_id,
        ).where(BalanceCarryForward.school_id == context.school_id)
    ).all()
    carries_from = {source_id: carry_id for carry_id, source_id, _destination_id in carry_rows}
    carries_into = {
        destination_id: carry_id for carry_id, _source_id, destination_id in carry_rows
    }
    return [
        {
            **_period_payload(
                period,
                activity_count=counts.get(period.id, 0) if include_activity else None,
            ),
            "has_close_snapshot": period.id in closed_snapshot_ids,
            "balance_carry_forward_id": carries_from.get(period.id),
            "balance_carried_forward": period.id in carries_from,
            "balance_carried_into": period.id in carries_into,
        }
        for period in periods
    ]


@router.get("/academic-periods/operational")
def operational_period(
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    period = resolve_period(session, school_id=context.school_id)
    return _period_payload(period)


@router.get("/academic-periods/{period_id}/close-readiness")
def period_close_readiness(
    period_id: uuid.UUID,
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    return _close_readiness(session, period)


@router.get("/academic-periods/{period_id}/close-summary")
def period_close_summary(
    period_id: uuid.UUID,
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
    include_learners: bool = False,
) -> dict:
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    statement = select(PeriodClose).where(
        PeriodClose.school_id == context.school_id, PeriodClose.period_id == period.id
    )
    if include_learners:
        statement = statement.options(selectinload(PeriodClose.learners))
    close = session.scalar(statement)
    if close is None:
        raise HTTPException(status_code=404, detail="This period does not have a closing snapshot")
    return _period_close_payload(close, include_learners=include_learners)


@router.get("/academic-periods/{period_id}/carry-forward-preview")
def balance_carry_forward_preview(
    period_id: uuid.UUID,
    destination_period_id: uuid.UUID,
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    existing = _load_balance_carry(
        session,
        school_id=context.school_id,
        source_period_id=period_id,
    )
    if existing is not None:
        if existing.destination_period_id != destination_period_id:
            raise HTTPException(
                status_code=409,
                detail="This source period has already been carried into another period",
            )
        return {
            "already_posted": True,
            "carry_forward": _balance_carry_payload(session, existing, include_lines=True),
        }
    _source, _destination, _close, _rows, preview = _carry_forward_preview(
        session,
        school_id=context.school_id,
        source_period_id=period_id,
        destination_period_id=destination_period_id,
    )
    return {"already_posted": False, **preview}


@router.get("/academic-periods/{period_id}/carry-forward")
def balance_carry_forward_summary(
    period_id: uuid.UUID,
    context: PeriodReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    resolve_period(session, school_id=context.school_id, period_id=period_id)
    carry = _load_balance_carry(
        session,
        school_id=context.school_id,
        source_period_id=period_id,
    )
    if carry is None:
        raise HTTPException(
            status_code=404,
            detail="Balances have not been carried from this period",
        )
    return _balance_carry_payload(session, carry, include_lines=True)


@router.post(
    "/academic-periods/{period_id}/carry-forward",
    status_code=status.HTTP_201_CREATED,
)
def post_balance_carry_forward(
    period_id: uuid.UUID,
    payload: BalanceCarryForwardCreate,
    response: Response,
    context: PeriodManageContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    existing = _load_balance_carry(
        session,
        school_id=context.school_id,
        source_period_id=period_id,
    )
    if existing is not None:
        if existing.destination_period_id != payload.destination_period_id:
            raise HTTPException(
                status_code=409,
                detail="This source period has already been carried into another period",
            )
        response.status_code = status.HTTP_200_OK
        return {
            **_balance_carry_payload(session, existing, include_lines=True),
            "idempotent_replay": True,
        }

    source = session.scalar(
        select(AcademicPeriod)
        .where(
            AcademicPeriod.id == period_id,
            AcademicPeriod.school_id == context.school_id,
        )
        .options(joinedload(AcademicPeriod.academic_year))
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source academic period not found")
    destination = session.scalar(
        select(AcademicPeriod)
        .where(
            AcademicPeriod.id == payload.destination_period_id,
            AcademicPeriod.school_id == context.school_id,
        )
        .options(joinedload(AcademicPeriod.academic_year))
        .with_for_update()
    )
    if destination is None:
        raise HTTPException(status_code=404, detail="Destination academic period not found")
    existing = _load_balance_carry(
        session,
        school_id=context.school_id,
        source_period_id=source.id,
    )
    if existing is not None:
        if existing.destination_period_id != destination.id:
            raise HTTPException(
                status_code=409,
                detail="This source period has already been carried into another period",
            )
        response.status_code = status.HTTP_200_OK
        return {
            **_balance_carry_payload(session, existing, include_lines=True),
            "idempotent_replay": True,
        }
    source, destination, close, rows, preview = _carry_forward_preview(
        session,
        school_id=context.school_id,
        source_period_id=source.id,
        destination_period_id=destination.id,
    )
    if not preview["ready_to_post"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{preview['conflicting_opening_count']} learner account(s) already have "
                "an explicit opening balance in the destination period"
            ),
        )
    occupied_destination = session.scalar(
        select(BalanceCarryForward.id).where(
            BalanceCarryForward.destination_period_id == destination.id
        )
    )
    if occupied_destination is not None:
        raise HTTPException(
            status_code=409,
            detail="The destination period already received a controlled balance carry",
        )
    carry = _create_balance_carry(
        session,
        school_id=context.school_id,
        source=source,
        destination=destination,
        close=close,
        rows=rows,
        idempotency_key=payload.idempotency_key,
        actor=context.actor,
    )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="balance_carry_forward",
            entity_id=carry.id,
            action="posted",
            actor=context.actor,
            summary=(
                f"Carried {carry.learner_count} learner balances from {source.name} "
                f"to {destination.name}"
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        existing = _load_balance_carry(
            session,
            school_id=context.school_id,
            source_period_id=period_id,
        ) or _load_balance_carry(
            session,
            school_id=context.school_id,
            idempotency_key=payload.idempotency_key,
        )
        if (
            existing is not None
            and existing.source_period_id == period_id
            and existing.destination_period_id == payload.destination_period_id
        ):
            response.status_code = status.HTTP_200_OK
            return {
                **_balance_carry_payload(session, existing, include_lines=True),
                "idempotent_replay": True,
            }
        raise HTTPException(
            status_code=409,
            detail="Balances could not be carried safely because the destination changed",
        ) from error
    session.refresh(carry)
    return {
        **_balance_carry_payload(session, carry, include_lines=True),
        "idempotent_replay": False,
    }


@router.post("/academic-years", status_code=status.HTTP_201_CREATED)
def create_academic_year(
    payload: AcademicYearCreate,
    context: PeriodManageContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    context.assert_school(payload.school_id)
    if session.get(School, context.school_id) is None:
        raise HTTPException(status_code=404, detail="School not found")
    year = AcademicYear(
        id=uuid.uuid4(),
        school_id=context.school_id,
        name=payload.name,
        year=payload.year,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status="draft",
    )
    year.periods = [
        AcademicPeriod(
            id=uuid.uuid4(),
            school_id=context.school_id,
            name=item.name,
            sequence=item.sequence,
            opening_date=item.opening_date,
            closing_date=item.closing_date,
            due_date=item.due_date,
            status="draft",
        )
        for item in payload.periods
    ]
    session.add(year)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="academic_year",
            entity_id=year.id,
            action="created",
            actor=context.actor,
            summary=f"Created {year.name} with {len(year.periods)} academic periods",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This academic year or one of its periods already exists"
        ) from error
    session.refresh(year)
    return {
        "id": year.id,
        "name": year.name,
        "year": year.year,
        "status": year.status,
        "periods": [_period_payload(period, activity_count=0) for period in year.periods],
    }


@router.put("/academic-periods/{period_id}")
def update_period(
    period_id: uuid.UUID,
    payload: AcademicPeriodUpdate,
    context: PeriodManageContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    if period.status == "closed":
        raise HTTPException(status_code=409, detail="Reopen this period before correcting it")
    year = period.academic_year
    if payload.opening_date < year.start_date or payload.closing_date > year.end_date:
        raise HTTPException(
            status_code=422, detail="The period must remain within its academic year"
        )
    sibling = session.scalar(
        select(AcademicPeriod.id).where(
            AcademicPeriod.academic_year_id == year.id,
            AcademicPeriod.id != period.id,
            AcademicPeriod.opening_date <= payload.closing_date,
            AcademicPeriod.closing_date >= payload.opening_date,
        )
    )
    if sibling is not None:
        raise HTTPException(status_code=422, detail="Academic periods cannot overlap")
    period.name = payload.name
    period.opening_date = payload.opening_date
    period.closing_date = payload.closing_date
    period.due_date = payload.due_date
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="academic_period",
            entity_id=period.id,
            action="corrected",
            actor=context.actor,
            summary=f"Corrected dates and name for {period.name}",
        )
    )
    session.commit()
    return _period_payload(period, activity_count=_activity_count(session, period.id))


@router.post("/academic-periods/{period_id}/transition")
def transition_period(
    period_id: uuid.UUID,
    payload: AcademicPeriodTransition,
    context: PeriodManageContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    if payload.status == "closed" and period.status == "closed":
        existing_close = session.scalar(
            select(PeriodClose).where(
                PeriodClose.school_id == context.school_id, PeriodClose.period_id == period.id
            )
        )
        if existing_close is None:
            raise HTTPException(
                status_code=409,
                detail="This legacy closed period has no controlled closing snapshot",
            )
        return {
            **_period_payload(period, activity_count=_activity_count(session, period.id)),
            "close_summary": _period_close_payload(existing_close),
            "idempotent_replay": True,
        }
    allowed = {
        "draft": {"open"},
        "open": {"closing"},
        "closing": {"closed"},
        "closed": {"open"},
    }
    if payload.status not in allowed[period.status]:
        raise HTTPException(
            status_code=409,
            detail=f"A {period.status} period cannot transition directly to {payload.status}",
        )
    if payload.status == "closed":
        period = session.scalar(
            select(AcademicPeriod)
            .where(
                AcademicPeriod.id == period_id,
                AcademicPeriod.school_id == context.school_id,
            )
            .options(joinedload(AcademicPeriod.academic_year))
            .with_for_update()
        )
        if period is None:
            raise HTTPException(status_code=404, detail="Academic period not found")
        if period.status == "closed":
            existing_close = session.scalar(
                select(PeriodClose).where(PeriodClose.period_id == period.id)
            )
            if existing_close is not None:
                return {
                    **_period_payload(period, activity_count=_activity_count(session, period.id)),
                    "close_summary": _period_close_payload(existing_close),
                    "idempotent_replay": True,
                }
        if period.status != "closing":
            raise HTTPException(
                status_code=409, detail=f"A {period.status} period cannot be closed"
            )
        readiness = _close_readiness(session, period)
        if not readiness["ready_to_close"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Resolve every pre-close blocker before closing this period",
                    "blocker_count": readiness["blocker_count"],
                    "controls": jsonable_encoder(
                        [item for item in readiness["controls"] if item["status"] == "blocked"]
                    ),
                },
            )
        close = _create_period_close(session, period, readiness, actor=context.actor)
    else:
        close = None
    if period.status == "closed":
        if context.role != "owner":
            raise HTTPException(
                status_code=403, detail="Only the institution owner can reopen a period"
            )
        if not payload.reason or not payload.reason.strip():
            raise HTTPException(status_code=422, detail="A reason is required to reopen a period")
        if session.scalar(select(PeriodClose.id).where(PeriodClose.period_id == period.id)):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This period has an immutable closing snapshot. Use the controlled reopening "
                    "workflow when it becomes available."
                ),
            )
    if payload.status == "open":
        other = session.scalar(
            select(AcademicPeriod.id).where(
                AcademicPeriod.school_id == context.school_id,
                AcademicPeriod.id != period.id,
                AcademicPeriod.status.in_(("open", "closing")),
            )
        )
        if other is not None:
            raise HTTPException(
                status_code=409,
                detail="Close the current operational period before opening another",
            )
    previous = period.status
    period.status = payload.status
    _refresh_year_status(period.academic_year)
    detail = f" ({payload.reason.strip()})" if payload.reason else ""
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="period_close" if close else "academic_period",
            entity_id=close.id if close else period.id,
            action="reopened" if previous == "closed" else payload.status,
            actor=context.actor,
            summary=(
                f"Closed {period.name} with {close.learner_count} learner snapshots "
                f"and hash {close.snapshot_hash[:12]}"
                if close
                else f"Changed {period.name} from {previous} to {payload.status}{detail}"
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if payload.status == "closed":
            existing_close = session.scalar(
                select(PeriodClose).where(
                    PeriodClose.school_id == context.school_id,
                    PeriodClose.period_id == period_id,
                )
            )
            if existing_close is not None:
                closed_period = resolve_period(
                    session, school_id=context.school_id, period_id=period_id
                )
                return {
                    **_period_payload(
                        closed_period,
                        activity_count=_activity_count(session, closed_period.id),
                    ),
                    "close_summary": _period_close_payload(existing_close),
                    "idempotent_replay": True,
                }
        raise HTTPException(
            status_code=409,
            detail=(
                "Period close could not be committed safely"
                if payload.status == "closed"
                else "Another operational period is already open"
            ),
        ) from error
    result = _period_payload(period, activity_count=_activity_count(session, period.id))
    if close:
        result["close_summary"] = _period_close_payload(close)
        result["idempotent_replay"] = False
    return result


@router.delete("/academic-periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_period(
    period_id: uuid.UUID,
    context: PeriodManageContext,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    if period.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft period can be deleted")
    if _activity_count(session, period.id):
        raise HTTPException(
            status_code=409,
            detail="A period containing financial or enrollment activity cannot be deleted",
        )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="academic_period",
            entity_id=period.id,
            action="deleted",
            actor=context.actor,
            summary=f"Deleted unused draft period {period.name}",
        )
    )
    session.delete(period)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
