import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.financial_reporting import load_student_financial_totals
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    ArrearsFollowUp,
    ArrearsPaymentPromise,
    AuditEvent,
    Enrollment,
    FeeCategory,
    FeeStructure,
    FeeStructureItem,
    FeeStructureLearner,
    GuardianLink,
    InstallmentRule,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    PaymentChannel,
    PaymentReceiptReissue,
    PaymentReceiptSequence,
    Person,
    Requirement,
    School,
    StellarAnchor,
    Stream,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import (
    ArrearAccount,
    ArrearsFollowUpCreate,
    ArrearsPromiseCancel,
    ArrearsRegister,
    FeeCategoryCreate,
    FeePlanCreate,
    FeeStructureSummary,
    PaymentChannelCreate,
    PaymentChannelUpdate,
    PaymentCorrectionCreate,
    PaymentCreate,
    PaymentSummary,
    ReceiptDetail,
    ReceiptReissueCreate,
)

router = APIRouter(prefix="/api/v1", tags=["finance"])


@router.get("/fee-categories")
def list_fee_categories(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
):
    context.assert_school(school_id)
    return session.scalars(
        select(FeeCategory)
        .where(FeeCategory.school_id == school_id, FeeCategory.is_active.is_(True))
        .order_by(FeeCategory.priority, FeeCategory.name)
    ).all()


@router.post("/fee-categories", status_code=status.HTTP_201_CREATED)
def create_fee_category(
    payload: FeeCategoryCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
):
    context.assert_school(payload.school_id)
    category = FeeCategory(**payload.model_dump(exclude={"code"}), code=payload.code.upper())
    session.add(category)
    try:
        session.flush()
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="fee_category",
                entity_id=category.id,
                action="created",
                actor=context.actor,
                summary=f"Created fee category {category.name}",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Fee category code already exists") from error
    session.refresh(category)
    return category


@router.post("/fee-plans", status_code=status.HTTP_201_CREATED)
def create_fee_plan(
    payload: FeePlanCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
):
    context.assert_school(payload.school_id)
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        academic_year=payload.academic_year,
        term=payload.term,
        writable=True,
    )
    academic_class = session.get(AcademicClass, payload.class_id)
    if academic_class is None or academic_class.school_id != payload.school_id:
        raise HTTPException(status_code=422, detail="Class does not belong to school")
    stream = session.get(Stream, payload.stream_id) if payload.stream_id else None
    if stream is not None and stream.class_id != payload.class_id:
        raise HTTPException(status_code=422, detail="Stream does not belong to the selected class")
    if payload.target_type == "cohort":
        existing_cohort = session.scalar(
            select(FeeStructure.id).where(
                FeeStructure.school_id == context.school_id,
                FeeStructure.period_id == period.id,
                FeeStructure.class_id == payload.class_id,
                FeeStructure.stream_id.is_(payload.stream_id)
                if payload.stream_id is None
                else FeeStructure.stream_id == payload.stream_id,
                FeeStructure.boarding_status.is_(payload.boarding_status)
                if payload.boarding_status is None
                else FeeStructure.boarding_status == payload.boarding_status,
                FeeStructure.target_type == "cohort",
                FeeStructure.is_active.is_(True),
            )
        )
        if existing_cohort:
            target = (
                "general fee for this class"
                if payload.stream_id is None and payload.boarding_status is None
                else "fee plan for this class target"
            )
            raise HTTPException(
                status_code=409,
                detail=f"An active {target} already exists in this academic period",
            )
    if payload.student_ids:
        eligible_ids = set(
            session.scalars(
                select(Student.id)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .where(
                    Student.school_id == payload.school_id,
                    Student.id.in_(payload.student_ids),
                    Student.status == "active",
                    Enrollment.period_id == period.id,
                    Enrollment.class_id == payload.class_id,
                )
            ).all()
        )
        if eligible_ids != set(payload.student_ids):
            raise HTTPException(
                status_code=422,
                detail="Every selected learner must be active in the plan class and period",
            )
    category_ids = {item.category_id for item in payload.items}
    valid_categories = set(
        session.scalars(
            select(FeeCategory.id).where(
                FeeCategory.school_id == payload.school_id, FeeCategory.id.in_(category_ids)
            )
        ).all()
    )
    if valid_categories != category_ids:
        raise HTTPException(status_code=422, detail="One or more fee categories are invalid")
    total = sum(item.amount for item in payload.items)
    plan = FeeStructure(
        school_id=payload.school_id,
        class_id=payload.class_id,
        stream_id=payload.stream_id,
        period_id=period.id,
        name=payload.name,
        academic_year=period.academic_year.year,
        term=period.sequence,
        currency=payload.currency,
        total_amount=total,
        target_type=payload.target_type,
        boarding_status=payload.boarding_status,
    )
    session.add(plan)
    try:
        session.flush()
        plan.items = [
            FeeStructureItem(category_id=item.category_id, amount=item.amount)
            for item in payload.items
        ]
        plan.installments = [
            InstallmentRule(
                name=item.name,
                amount=item.calculated_amount(total),
                calculation_type=item.calculation_type,
                percentage=item.percentage,
                due_date=item.due_date,
                sort_order=item.sort_order,
            )
            for item in payload.installments
        ]
        plan.selected_learners = [
            FeeStructureLearner(student_id=student_id) for student_id in payload.student_ids
        ]
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="fee_structure",
                entity_id=plan.id,
                action="created",
                actor=context.actor,
                summary=f"Created {plan.name} totaling {plan.total_amount} {plan.currency}",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This fee plan conflicts with existing configuration"
        ) from error
    return {"id": plan.id, "total_amount": plan.total_amount}


@router.get("/fee-structures", response_model=list[FeeStructureSummary])
def list_fee_structures(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    items = session.scalars(
        select(FeeStructure)
        .where(
            FeeStructure.school_id == school_id,
            FeeStructure.period_id == period.id,
            FeeStructure.is_active.is_(True),
        )
        .options(
            selectinload(FeeStructure.selected_learners),
            selectinload(FeeStructure.installments),
        )
        .order_by(FeeStructure.name)
    ).all()
    return [
        FeeStructureSummary(
            id=item.id,
            class_id=item.class_id,
            stream_id=item.stream_id,
            name=item.name,
            academic_year=item.academic_year,
            term=item.term,
            currency=item.currency,
            total_amount=item.total_amount,
            target_type=item.target_type,
            boarding_status=item.boarding_status,
            status=item.status,
            is_general=(
                item.target_type == "cohort"
                and item.stream_id is None
                and item.boarding_status is None
            ),
            selected_learner_count=len(item.selected_learners),
            installments=[
                {
                    "id": rule.id,
                    "name": rule.name,
                    "amount": rule.amount,
                    "calculation_type": rule.calculation_type,
                    "percentage": rule.percentage,
                    "due_date": rule.due_date,
                    "sort_order": rule.sort_order,
                }
                for rule in sorted(item.installments, key=lambda value: value.sort_order)
            ],
        )
        for item in items
    ]


@router.delete("/fee-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_fee_plan(
    plan_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> Response:
    plan = session.scalar(
        select(FeeStructure).where(
            FeeStructure.id == plan_id,
            FeeStructure.school_id == context.school_id,
            FeeStructure.is_active.is_(True),
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Fee plan not found")
    resolve_period(session, school_id=context.school_id, period_id=plan.period_id, writable=True)
    assignment_count = session.scalar(
        select(func.count(StudentFeeAssignment.id)).where(
            StudentFeeAssignment.fee_structure_id == plan.id
        )
    )
    if plan.status != "draft" or assignment_count:
        raise HTTPException(status_code=409, detail="Published fee plans cannot be removed")
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="fee_structure",
            entity_id=plan.id,
            action="deleted",
            actor=context.actor,
            summary=f"Deleted draft fee plan {plan.name}",
        )
    )
    session.delete(plan)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/arrears", response_model=ArrearsRegister)
def list_arrears(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    as_of: date | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
    class_id: uuid.UUID | None = None,
    stream_id: uuid.UUID | None = None,
    boarding_status: str | None = None,
    fee_category_id: uuid.UUID | None = None,
    severity: str | None = None,
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    cutoff = as_of or date.today()
    accounts: list[ArrearAccount] = []
    students = session.scalars(
        select(Student)
        .where(Student.school_id == school_id, Student.status == "active")
        .order_by(Student.admission_no)
        .options(
            joinedload(Student.person),
            selectinload(Student.enrollments).joinedload(Enrollment.academic_class),
            selectinload(Student.enrollments).joinedload(Enrollment.stream),
            selectinload(Student.guardians).joinedload(GuardianLink.person),
            selectinload(Student.fee_assignments)
            .joinedload(StudentFeeAssignment.fee_structure)
            .selectinload(FeeStructure.installments),
            selectinload(Student.fee_assignments)
            .joinedload(StudentFeeAssignment.fee_structure)
            .selectinload(FeeStructure.items)
            .joinedload(FeeStructureItem.category),
        )
    ).all()
    paid_by_student = dict(
        session.execute(
            select(
                PaymentAllocation.student_id,
                func.coalesce(func.sum(PaymentAllocation.amount), 0),
            )
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .join(Student, Student.id == PaymentAllocation.student_id)
            .where(
                Student.school_id == school_id,
                Payment.period_id == period.id,
            )
            .group_by(PaymentAllocation.student_id)
        ).all()
    )
    eligible_period_ids = session.scalars(
        select(AcademicPeriod.id)
        .join(AcademicYear, AcademicYear.id == AcademicPeriod.academic_year_id)
        .where(
            AcademicPeriod.school_id == school_id,
            (AcademicYear.year < period.academic_year.year)
            | (
                (AcademicYear.year == period.academic_year.year)
                & (AcademicPeriod.sequence <= period.sequence)
            ),
        )
    ).all()
    ledger_balances = dict(
        session.execute(
            select(LedgerEntry.student_id, func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(
                LedgerEntry.school_id == school_id,
                LedgerEntry.period_id.in_(eligible_period_ids),
            )
            .group_by(LedgerEntry.student_id)
        ).all()
    )
    requirement_rows: dict[uuid.UUID, list[tuple[StudentRequirement, Requirement]]] = {}
    for assignment, requirement in session.execute(
        select(StudentRequirement, Requirement)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(
            Requirement.school_id == school_id,
            Requirement.period_id == period.id,
            Requirement.requirement_type.in_(("payment", "school_item")),
            StudentRequirement.is_waived.is_(False),
        )
    ).all():
        requirement_rows.setdefault(assignment.student_id, []).append((assignment, requirement))
    nonpayment_credits = dict(
        session.execute(
            select(LedgerEntry.student_id, func.coalesce(func.sum(-LedgerEntry.amount), 0))
            .where(
                LedgerEntry.school_id == school_id,
                LedgerEntry.period_id == period.id,
                LedgerEntry.amount < 0,
                LedgerEntry.entry_type != "payment",
            )
            .group_by(LedgerEntry.student_id)
        ).all()
    )
    latest_followups: dict[uuid.UUID, ArrearsFollowUp] = {}
    for followup in session.scalars(
        select(ArrearsFollowUp)
        .where(ArrearsFollowUp.school_id == school_id, ArrearsFollowUp.period_id == period.id)
        .order_by(ArrearsFollowUp.created_at.desc(), ArrearsFollowUp.id.desc())
    ).all():
        latest_followups.setdefault(followup.student_id, followup)
    promises_by_student: dict[uuid.UUID, ArrearsPaymentPromise] = {}
    for promise in session.scalars(
        select(ArrearsPaymentPromise)
        .where(
            ArrearsPaymentPromise.school_id == school_id,
            ArrearsPaymentPromise.period_id == period.id,
            ArrearsPaymentPromise.status == "active",
        )
        .order_by(ArrearsPaymentPromise.created_at.desc(), ArrearsPaymentPromise.id.desc())
    ).all():
        promises_by_student.setdefault(promise.student_id, promise)
    for student in students:
        assignments = [
            assignment
            for assignment in student.fee_assignments
            if assignment.fee_structure and assignment.fee_structure.period_id == period.id
        ]
        if not assignments:
            continue
        billed = sum((assignment.amount for assignment in assignments), Decimal("0"))
        paid = paid_by_student.get(student.id, Decimal("0"))
        due_events: list[dict] = []
        for assignment in assignments:
            structure = assignment.fee_structure
            if structure is None or not structure.total_amount:
                continue
            installments = sorted(
                structure.installments, key=lambda item: (item.due_date, item.sort_order)
            ) or [
                type("Due", (), {"due_date": period.due_date, "amount": structure.total_amount})()
            ]
            items = structure.items or [
                type(
                    "Item",
                    (),
                    {"amount": structure.total_amount, "category_id": None, "category": None},
                )()
            ]
            for installment in installments:
                installment_value = installment.amount * assignment.amount / structure.total_amount
                for item in items:
                    value = installment_value * item.amount / structure.total_amount
                    due_events.append(
                        {
                            "due_date": installment.due_date,
                            "amount": value,
                            "category_id": item.category_id,
                            "reason": item.category.name if item.category else structure.name,
                        }
                    )
        for requirement_assignment, requirement in requirement_rows.get(student.id, []):
            billed += requirement_assignment.expected_amount
            due_events.append(
                {
                    "due_date": requirement.due_date or period.due_date,
                    "amount": requirement_assignment.expected_amount,
                    "category_id": None,
                    "reason": requirement.name,
                }
            )
        balance = ledger_balances.get(student.id, billed - paid)
        balance = max(balance, Decimal("0"))
        if balance <= 0:
            continue
        scheduled = sum((event["amount"] for event in due_events), Decimal("0"))
        reduction = min(paid + nonpayment_credits.get(student.id, Decimal("0")), scheduled)
        remaining_events: list[dict] = []
        for event in sorted(due_events, key=lambda item: item["due_date"]):
            consumed = min(reduction, event["amount"])
            reduction -= consumed
            remaining = event["amount"] - consumed
            if remaining > 0:
                remaining_events.append(event | {"amount": remaining})
        overdue_events = [event for event in remaining_events if event["due_date"] < cutoff]
        overdue_amount = sum((event["amount"] for event in overdue_events), Decimal("0"))
        overdue_amount = min(overdue_amount, balance)
        overdue_since = min((event["due_date"] for event in overdue_events), default=None)
        if overdue_amount <= 0 or overdue_since is None:
            continue
        person = student.person
        enrollment = next(
            (item for item in student.enrollments if item.period_id == period.id), None
        )
        academic_class = enrollment.academic_class if enrollment else None
        stream = enrollment.stream if enrollment else None
        if class_id and (not enrollment or enrollment.class_id != class_id):
            continue
        if stream_id and (not enrollment or enrollment.stream_id != stream_id):
            continue
        if boarding_status and student.boarding_status != boarding_status:
            continue
        if fee_category_id and not any(
            event["category_id"] == fee_category_id for event in remaining_events
        ):
            continue
        guardian_link = next(
            (item for item in student.guardians if item.is_primary),
            student.guardians[0] if student.guardians else None,
        )
        days_overdue = (cutoff - overdue_since).days
        aging = {
            "current": Decimal("0"),
            "1_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "90_plus": Decimal("0"),
        }
        reason_totals: dict[tuple[uuid.UUID | None, str], Decimal] = {}
        for event in remaining_events:
            age = (cutoff - event["due_date"]).days
            band = (
                "current"
                if age <= 0
                else "1_30"
                if age <= 30
                else "31_60"
                if age <= 60
                else "61_90"
                if age <= 90
                else "90_plus"
            )
            aging[band] += event["amount"]
            reason_key = (event["category_id"], event["reason"])
            reason_totals[reason_key] = (
                reason_totals.get(reason_key, Decimal("0")) + event["amount"]
            )
        aging_band = (
            "90_plus"
            if aging["90_plus"]
            else "61_90"
            if aging["61_90"]
            else "31_60"
            if aging["31_60"]
            else "1_30"
        )
        account_severity = (
            "critical" if days_overdue > 60 else "high" if days_overdue > 30 else "warning"
        )
        if severity and account_severity != severity:
            continue
        latest = latest_followups.get(student.id)
        promise = promises_by_student.get(student.id)
        promise_payload = _promise_payload(promise, paid, cutoff) if promise else None
        guardian = guardian_link.person if guardian_link else None
        accounts.append(
            ArrearAccount(
                student_id=student.id,
                admission_no=student.admission_no,
                student_name=f"{person.first_name} {person.last_name}",
                class_name=academic_class.name if academic_class else "Unplaced",
                class_id=academic_class.id if academic_class else None,
                stream_name=stream.name if stream else None,
                stream_id=stream.id if stream else None,
                boarding_status=student.boarding_status,
                guardian_name=(f"{guardian.first_name} {guardian.last_name}" if guardian else None),
                guardian_phone=guardian.phone if guardian else None,
                billed=billed,
                paid=paid,
                balance=balance,
                overdue_amount=overdue_amount,
                overdue_since=overdue_since,
                days_overdue=days_overdue,
                severity=account_severity,
                aging_band=aging_band,
                aging=aging,
                reasons=[
                    {"category_id": category_id, "name": name, "amount": amount}
                    for (category_id, name), amount in sorted(
                        reason_totals.items(), key=lambda item: item[1], reverse=True
                    )
                ],
                last_contact_at=latest.created_at if latest else None,
                next_action=latest.next_action if latest else None,
                next_action_date=latest.next_action_date if latest else None,
                active_promise=promise_payload,
            )
        )
    accounts.sort(key=lambda item: (item.days_overdue, item.overdue_amount), reverse=True)
    totals = {
        key: sum((item.aging.get(key, Decimal("0")) for item in accounts), Decimal("0"))
        for key in ("current", "1_30", "31_60", "61_90", "90_plus")
    }
    return ArrearsRegister(
        as_of=cutoff,
        total_accounts=len(accounts),
        total_overdue=sum((item.overdue_amount for item in accounts), Decimal("0")),
        critical_accounts=sum(item.severity in {"critical", "high"} for item in accounts),
        aging=totals,
        items=accounts,
    )


def _promise_payload(promise: ArrearsPaymentPromise, current_paid: Decimal, cutoff: date) -> dict:
    received = max(current_paid - promise.paid_at_creation, Decimal("0"))
    if promise.status == "cancelled":
        derived_status = "cancelled"
    elif received >= promise.promised_amount:
        derived_status = "kept"
    elif promise.due_date < cutoff:
        derived_status = "broken"
    elif received > 0:
        derived_status = "partially_kept"
    else:
        derived_status = "active"
    return {
        "id": promise.id,
        "promised_amount": promise.promised_amount,
        "received_since": received,
        "due_date": promise.due_date,
        "status": derived_status,
    }


def _period_paid(session: Session, period_id: uuid.UUID, student_id: uuid.UUID) -> Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(Payment.period_id == period_id, PaymentAllocation.student_id == student_id)
    ) or Decimal("0")


def _followup_payload(
    followup: ArrearsFollowUp,
    promise: ArrearsPaymentPromise | None,
    current_paid: Decimal,
    cutoff: date,
) -> dict:
    return {
        "id": followup.id,
        "contact_method": followup.contact_method,
        "contacted_person": followup.contacted_person,
        "outcome": followup.outcome,
        "note": followup.note,
        "next_action": followup.next_action,
        "next_action_date": followup.next_action_date,
        "created_by": followup.created_by,
        "created_at": followup.created_at,
        "promise": _promise_payload(promise, current_paid, cutoff) if promise else None,
    }


@router.get("/arrears/{student_id}/follow-ups")
def list_arrears_followups(
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    as_of: date | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
):
    context.assert_school(school_id)
    resolve_period(session, school_id=school_id, period_id=period_id)
    student = session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner account not found")
    followups = session.scalars(
        select(ArrearsFollowUp)
        .where(
            ArrearsFollowUp.school_id == school_id,
            ArrearsFollowUp.period_id == period_id,
            ArrearsFollowUp.student_id == student_id,
        )
        .order_by(ArrearsFollowUp.created_at.desc(), ArrearsFollowUp.id.desc())
    ).all()
    promises = {
        item.follow_up_id: item
        for item in session.scalars(
            select(ArrearsPaymentPromise).where(
                ArrearsPaymentPromise.school_id == school_id,
                ArrearsPaymentPromise.period_id == period_id,
                ArrearsPaymentPromise.student_id == student_id,
            )
        ).all()
    }
    paid = _period_paid(session, period_id, student_id)
    cutoff = as_of or date.today()
    return {
        "items": [
            _followup_payload(item, promises.get(item.id), paid, cutoff) for item in followups
        ]
    }


@router.post("/arrears/follow-ups", status_code=status.HTTP_201_CREATED)
def create_arrears_followup(
    payload: ArrearsFollowUpCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
):
    context.assert_school(payload.school_id)
    resolve_period(session, school_id=payload.school_id, period_id=payload.period_id, writable=True)
    existing = session.scalar(
        select(ArrearsFollowUp).where(
            ArrearsFollowUp.school_id == payload.school_id,
            ArrearsFollowUp.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.student_id != payload.student_id or existing.period_id != payload.period_id:
            raise HTTPException(status_code=409, detail="Follow-up key was already used")
        promise = session.scalar(
            select(ArrearsPaymentPromise).where(ArrearsPaymentPromise.follow_up_id == existing.id)
        )
        paid = _period_paid(session, payload.period_id, payload.student_id)
        return _followup_payload(existing, promise, paid, date.today())
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
        raise HTTPException(status_code=422, detail="Learner has no overdue balance to follow up")
    if bool(payload.next_action) != bool(payload.next_action_date):
        raise HTTPException(
            status_code=422, detail="Next action and next action date must be provided together"
        )
    if bool(payload.promised_amount) != bool(payload.promised_due_date):
        raise HTTPException(
            status_code=422, detail="Promise amount and promise due date must be provided together"
        )
    if payload.promised_amount and payload.outcome != "commitment":
        raise HTTPException(status_code=422, detail="A payment promise requires commitment outcome")
    if payload.promised_amount and payload.promised_amount > account.balance:
        raise HTTPException(status_code=422, detail="Promise cannot exceed the learner balance")
    if payload.promised_due_date and payload.promised_due_date < date.today():
        raise HTTPException(status_code=422, detail="Promise due date cannot be in the past")
    followup = ArrearsFollowUp(
        school_id=payload.school_id,
        period_id=payload.period_id,
        student_id=payload.student_id,
        contact_method=payload.contact_method,
        contacted_person=payload.contacted_person.strip(),
        outcome=payload.outcome,
        note=payload.note.strip(),
        next_action=payload.next_action.strip() if payload.next_action else None,
        next_action_date=payload.next_action_date,
        idempotency_key=payload.idempotency_key,
        created_by=context.actor,
    )
    session.add(followup)
    session.flush()
    promise = None
    paid = _period_paid(session, payload.period_id, payload.student_id)
    if payload.promised_amount and payload.promised_due_date:
        promise = ArrearsPaymentPromise(
            follow_up_id=followup.id,
            school_id=payload.school_id,
            period_id=payload.period_id,
            student_id=payload.student_id,
            promised_amount=payload.promised_amount,
            paid_at_creation=paid,
            due_date=payload.promised_due_date,
            created_by=context.actor,
        )
        session.add(promise)
    session.add(
        AuditEvent(
            school_id=payload.school_id,
            entity_type="arrears_follow_up",
            entity_id=followup.id,
            action="created",
            actor=context.actor,
            summary=(
                f"Recorded {payload.contact_method} arrears follow-up for {account.admission_no}"
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Follow-up was already recorded") from error
    session.refresh(followup)
    if promise:
        session.refresh(promise)
    return _followup_payload(followup, promise, paid, date.today())


@router.post("/arrears/promises/{promise_id}/cancel")
def cancel_arrears_promise(
    promise_id: uuid.UUID,
    payload: ArrearsPromiseCancel,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
):
    promise = session.scalar(
        select(ArrearsPaymentPromise).where(
            ArrearsPaymentPromise.id == promise_id,
            ArrearsPaymentPromise.school_id == context.school_id,
        )
    )
    if promise is None:
        raise HTTPException(status_code=404, detail="Payment promise not found")
    if promise.status == "cancelled":
        return _promise_payload(
            promise, _period_paid(session, promise.period_id, promise.student_id), date.today()
        )
    promise.status = "cancelled"
    promise.cancellation_reason = payload.reason.strip()
    promise.cancelled_by = context.actor
    promise.cancelled_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=promise.school_id,
            entity_type="arrears_payment_promise",
            entity_id=promise.id,
            action="cancelled",
            actor=context.actor,
            summary=f"Cancelled payment promise: {payload.reason.strip()}",
        )
    )
    session.commit()
    return _promise_payload(
        promise, _period_paid(session, promise.period_id, promise.student_id), date.today()
    )


@router.get("/arrears-worklist.csv")
def arrears_worklist_csv(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    as_of: date | None = None,
    class_id: uuid.UUID | None = None,
    stream_id: uuid.UUID | None = None,
    boarding_status: str | None = None,
    fee_category_id: uuid.UUID | None = None,
    severity: str | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
):
    register = list_arrears(
        school_id,
        period_id,
        as_of,
        session,
        context,
        class_id,
        stream_id,
        boarding_status,
        fee_category_id,
        severity,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Admission no",
            "Learner",
            "Class",
            "Stream",
            "Residence",
            "Guardian",
            "Phone",
            "Reason",
            "Balance",
            "Overdue",
            "Aging",
            "Last contact",
            "Next action",
            "Action due",
            "Promise",
            "Promise due",
            "Promise status",
        ]
    )
    for item in register.items:
        promise = item.active_promise or {}
        writer.writerow(
            [
                item.admission_no,
                item.student_name,
                item.class_name,
                item.stream_name or "",
                item.boarding_status,
                item.guardian_name or "",
                item.guardian_phone or "",
                "; ".join(reason["name"] for reason in item.reasons),
                item.balance,
                item.overdue_amount,
                item.aging_band,
                item.last_contact_at.isoformat() if item.last_contact_at else "",
                item.next_action or "",
                item.next_action_date or "",
                promise.get("promised_amount", ""),
                promise.get("due_date", ""),
                promise.get("status", ""),
            ]
        )
    headers = {"Content-Disposition": f'attachment; filename="arrears-{register.as_of}.csv"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


def _overdue_position(
    due_events: list[tuple[date, Decimal]], paid: Decimal, cutoff: date
) -> tuple[Decimal, date | None]:
    events = sorted((due_date, amount) for due_date, amount in due_events if due_date <= cutoff)
    expected = sum((amount for _, amount in events), Decimal("0"))
    overdue = max(expected - paid, Decimal("0"))
    if overdue <= 0:
        return Decimal("0"), None
    remaining_credit = paid
    for due_date, due_amount in events:
        if remaining_credit >= due_amount:
            remaining_credit -= due_amount
        else:
            return overdue, due_date
    return overdue, cutoff


STANDARD_CHANNELS = {
    "cash": {"label": "Cash", "requires_reference": False},
    "bank": {"label": "Bank deposit / transfer", "requires_reference": True},
    "mobile_money": {"label": "Mobile Money", "requires_reference": True},
    "schoolpay": {"label": "SchoolPay", "requires_reference": True},
    "card": {"label": "Card", "requires_reference": True},
    "sponsor": {"label": "Sponsor", "requires_reference": True},
}


def _next_payment_receipt(session: Session, school_id: uuid.UUID) -> str:
    session.scalar(select(School.id).where(School.id == school_id).with_for_update())
    counter = session.get(PaymentReceiptSequence, school_id)
    if counter is None:
        counter = PaymentReceiptSequence(school_id=school_id, next_number=1)
        session.add(counter)
        session.flush()
    number = counter.next_number
    counter.next_number += 1
    return f"H1-{datetime.now(UTC).year}-{school_id.hex[:4].upper()}-{number:06d}"


def _payment_allocations(session: Session, payment_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(PaymentAllocation, Requirement)
        .outerjoin(
            StudentRequirement,
            StudentRequirement.id == PaymentAllocation.requirement_assignment_id,
        )
        .outerjoin(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(PaymentAllocation.payment_id == payment_id)
        .order_by(PaymentAllocation.id)
    ).all()
    return [
        {
            "id": allocation.id,
            "allocation_type": allocation.allocation_type,
            "amount": allocation.amount,
            "purpose": (
                requirement.name
                if requirement
                else "Unallocated learner credit"
                if allocation.allocation_type == "unallocated"
                else "School fees"
            ),
            "requirement_assignment_id": allocation.requirement_assignment_id,
        }
        for allocation, requirement in rows
    ]


def _payment_summary(session: Session, payment: Payment) -> PaymentSummary:
    allocations = _payment_allocations(session, payment.id)
    first = session.scalar(
        select(PaymentAllocation)
        .where(PaymentAllocation.payment_id == payment.id)
        .order_by(PaymentAllocation.id)
    )
    if first is None:
        raise HTTPException(status_code=409, detail="Payment allocation is incomplete")
    student = session.get(Student, first.student_id)
    person = session.get(Person, student.person_id) if student else None
    anchor = session.scalar(select(StellarAnchor).where(StellarAnchor.payment_id == payment.id))
    if student is None or person is None or anchor is None:
        raise HTTPException(status_code=409, detail="Payment record is incomplete")
    purpose = (
        allocations[0]["purpose"] if len(allocations) == 1 else f"{len(allocations)} allocations"
    )
    return PaymentSummary(
        id=payment.id,
        receipt_no=payment.receipt_no,
        external_reference=payment.external_reference,
        student_name=f"{person.first_name} {person.last_name}",
        admission_no=student.admission_no,
        channel=payment.channel,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        transaction_type=payment.transaction_type,
        original_payment_id=payment.original_payment_id,
        correction_reason=payment.correction_reason,
        purpose=purpose,
        allocations=allocations,
        stellar_status=anchor.status,
        commitment_hash=anchor.commitment_hash,
        received_at=payment.received_at.isoformat(),
    )


def _learner_obligations(
    session: Session, *, school_id: uuid.UUID, period_id: uuid.UUID, student_id: uuid.UUID
) -> dict:
    student = session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    requirement_rows = session.execute(
        select(StudentRequirement, Requirement)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(
            StudentRequirement.student_id == student_id,
            Requirement.period_id == period_id,
            Requirement.requirement_type.in_(("payment", "school_item")),
            StudentRequirement.is_waived.is_(False),
        )
        .order_by(Requirement.name)
    ).all()
    requirements = []
    for assignment, requirement in requirement_rows:
        allocated = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.requirement_assignment_id == assignment.id
            )
        ) or Decimal("0")
        outstanding = max(assignment.expected_amount - allocated, Decimal("0"))
        if outstanding > 0:
            requirements.append(
                {
                    "id": assignment.id,
                    "label": requirement.name,
                    "expected": assignment.expected_amount,
                    "paid": allocated,
                    "outstanding": outstanding,
                }
            )
    fee_base = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.school_id == school_id,
            LedgerEntry.period_id == period_id,
            LedgerEntry.student_id == student_id,
            LedgerEntry.entry_type.notin_(("payment", "reversal", "refund", "requirement_charge")),
        )
    ) or Decimal("0")
    fee_paid = session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(
            Payment.school_id == school_id,
            Payment.period_id == period_id,
            PaymentAllocation.student_id == student_id,
            PaymentAllocation.allocation_type == "fees",
        )
    ) or Decimal("0")
    unallocated = session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(
            Payment.school_id == school_id,
            Payment.period_id == period_id,
            PaymentAllocation.student_id == student_id,
            PaymentAllocation.allocation_type == "unallocated",
        )
    ) or Decimal("0")
    account_balance = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.school_id == school_id,
            LedgerEntry.period_id == period_id,
            LedgerEntry.student_id == student_id,
        )
    ) or Decimal("0")
    return {
        "student_id": student.id,
        "fees": {
            "label": "School fees",
            "billed": fee_base,
            "paid": fee_paid,
            "outstanding": max(fee_base - fee_paid, Decimal("0")),
        },
        "requirements": requirements,
        "account_balance": max(account_balance, Decimal("0")),
        "account_credit": max(-account_balance, Decimal("0")),
        "unallocated_credit": max(unallocated, Decimal("0")),
    }


@router.get("/payment-desk/learners")
def search_payment_learners(
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    q: str = "",
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    context.assert_school(school_id)
    resolve_period(session, school_id=school_id, period_id=period_id)
    term = q.strip()
    query = (
        select(Student, Person, AcademicClass, Stream)
        .join(Person, Person.id == Student.person_id)
        .join(
            Enrollment,
            (Enrollment.student_id == Student.id) & (Enrollment.period_id == period_id),
        )
        .join(AcademicClass, AcademicClass.id == Enrollment.class_id)
        .outerjoin(Stream, Stream.id == Enrollment.stream_id)
        .where(Student.school_id == school_id, Student.status == "active")
    )
    if term:
        guardian_people = (
            select(GuardianLink.student_id)
            .join(Person, Person.id == GuardianLink.person_id)
            .where(
                or_(
                    Person.first_name.ilike(f"%{term}%"),
                    Person.last_name.ilike(f"%{term}%"),
                    Person.phone.ilike(f"%{term}%"),
                )
            )
        )
        query = query.where(
            or_(
                Student.admission_no.ilike(f"%{term}%"),
                Student.learner_identification_number.ilike(f"%{term}%"),
                Person.first_name.ilike(f"%{term}%"),
                Person.last_name.ilike(f"%{term}%"),
                Student.id.in_(guardian_people),
            )
        )
    rows = session.execute(query.distinct().order_by(Student.admission_no).limit(30)).all()
    return [
        {
            "id": student.id,
            "admission_no": student.admission_no,
            "full_name": f"{person.first_name} {person.last_name}",
            "class_name": academic_class.name,
            "stream_name": stream.name if stream else None,
        }
        for student, person, academic_class, stream in rows
    ]


@router.get("/payment-desk/learners/{student_id}/obligations")
def payment_learner_obligations(
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    context.assert_school(school_id)
    resolve_period(session, school_id=school_id, period_id=period_id)
    return _learner_obligations(
        session, school_id=school_id, period_id=period_id, student_id=student_id
    )


@router.get("/payment-channels")
def list_payment_channels(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    context.assert_school(school_id)
    channels = session.scalars(
        select(PaymentChannel)
        .where(PaymentChannel.school_id == school_id)
        .order_by(PaymentChannel.label)
    ).all()
    if channels:
        return channels
    channels = [
        PaymentChannel(
            school_id=school_id,
            code=code,
            label=preset["label"],
            channel_type=code if code != "sponsor" else "other",
            requires_reference=preset["requires_reference"],
            created_by=context.actor,
        )
        for code, preset in STANDARD_CHANNELS.items()
    ]
    session.add_all(channels)
    session.commit()
    return sorted(channels, key=lambda item: item.label)


@router.post("/payment-channels", status_code=status.HTTP_201_CREATED)
def create_payment_channel(
    payload: PaymentChannelCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    context.assert_school(payload.school_id)
    if context.role == "cashier":
        raise HTTPException(status_code=403, detail="Cashiers cannot configure payment channels")
    channel = PaymentChannel(
        **payload.model_dump(exclude={"code"}),
        code=payload.code.strip().lower(),
        created_by=context.actor,
    )
    session.add(channel)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Payment channel code already exists"
        ) from error
    session.refresh(channel)
    return channel


@router.patch("/payment-channels/{channel_id}")
def update_payment_channel(
    channel_id: uuid.UUID,
    payload: PaymentChannelUpdate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    if context.role == "cashier":
        raise HTTPException(status_code=403, detail="Cashiers cannot configure payment channels")
    channel = session.scalar(
        select(PaymentChannel).where(
            PaymentChannel.id == channel_id, PaymentChannel.school_id == context.school_id
        )
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Payment channel not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(channel, key, value)
    session.commit()
    session.refresh(channel)
    return channel


@router.get("/payments", response_model=list[PaymentSummary])
def list_payments(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    rows = session.scalars(
        select(Payment)
        .where(Payment.school_id == school_id, Payment.period_id == period.id)
        .order_by(Payment.received_at.desc(), Payment.id.desc())
        .limit(200)
    ).all()
    return [_payment_summary(session, payment) for payment in rows]


def _resolved_allocations(
    session: Session,
    *,
    payload: PaymentCreate,
    period_id: uuid.UUID,
    student: Student,
) -> list[dict]:
    obligations = _learner_obligations(
        session,
        school_id=student.school_id,
        period_id=period_id,
        student_id=student.id,
    )
    requested = list(payload.allocations)
    if not requested and payload.requirement_assignment_id:
        from harambeeone_api.schemas import PaymentAllocationCreate

        requested = [
            PaymentAllocationCreate(
                allocation_type="requirement",
                amount=payload.amount,
                requirement_assignment_id=payload.requirement_assignment_id,
            )
        ]
    if not requested:
        from harambeeone_api.schemas import PaymentAllocationCreate

        fee_amount = min(payload.amount, obligations["fees"]["outstanding"])
        if fee_amount:
            requested.append(PaymentAllocationCreate(allocation_type="fees", amount=fee_amount))
        if payload.amount > fee_amount:
            requested.append(
                PaymentAllocationCreate(
                    allocation_type="unallocated", amount=payload.amount - fee_amount
                )
            )
    if sum((item.amount for item in requested), Decimal("0")) != payload.amount:
        raise HTTPException(status_code=422, detail="Allocations must equal the payment amount")
    seen_targets: set[tuple[str, uuid.UUID | None]] = set()
    requirement_map = {item["id"]: item for item in obligations["requirements"]}
    result = []
    for item in requested:
        key = (item.allocation_type, item.requirement_assignment_id)
        if key in seen_targets:
            raise HTTPException(status_code=422, detail="Combine duplicate allocation targets")
        seen_targets.add(key)
        if item.allocation_type == "fees" and item.amount > obligations["fees"]["outstanding"]:
            raise HTTPException(
                status_code=422,
                detail="Fee allocation exceeds the open fee balance",
            )
        if item.allocation_type == "requirement":
            obligation = requirement_map.get(item.requirement_assignment_id)
            if obligation is None:
                raise HTTPException(
                    status_code=422,
                    detail="Requirement is not an open learner obligation",
                )
            if item.amount > obligation["outstanding"]:
                raise HTTPException(
                    status_code=422,
                    detail=f"Allocation exceeds the {obligation['label']} balance",
                )
        result.append(item.model_dump())
    return result


@router.post("/payments", response_model=PaymentSummary, status_code=status.HTTP_201_CREATED)
def record_payment(
    payload: PaymentCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
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
    configured_channel = session.scalar(
        select(PaymentChannel).where(
            PaymentChannel.school_id == context.school_id,
            PaymentChannel.code == payload.channel,
            PaymentChannel.is_active.is_(True),
        )
    )
    standard = STANDARD_CHANNELS.get(payload.channel)
    if configured_channel is None and standard is None:
        raise HTTPException(status_code=422, detail="Choose an active school payment channel")
    requires_reference = (
        configured_channel.requires_reference
        if configured_channel
        else standard["requires_reference"]
    )
    if requires_reference and not payload.external_reference:
        raise HTTPException(
            status_code=422,
            detail="This payment channel requires a source reference",
        )
    reference = (
        payload.external_reference.strip().upper()
        if payload.external_reference
        else f"CASH-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"
    )
    existing = session.scalar(
        select(Payment).where(
            Payment.school_id == context.school_id,
            Payment.external_reference == reference,
        )
    )
    if existing is not None:
        existing_student_id = session.scalar(
            select(PaymentAllocation.student_id).where(PaymentAllocation.payment_id == existing.id)
        )
        if (
            existing.transaction_type == "receipt"
            and existing_student_id == student.id
            and existing.amount == payload.amount
            and existing.channel == payload.channel
        ):
            return _payment_summary(session, existing)
        raise HTTPException(
            status_code=409, detail="This payment reference has already been recorded"
        )
    allocations = _resolved_allocations(
        session, payload=payload, period_id=period.id, student=student
    )
    payment = Payment(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=period.id,
        receipt_no=_next_payment_receipt(session, context.school_id),
        external_reference=reference,
        payer_name=payload.payer_name.strip() if payload.payer_name else None,
        note=payload.note.strip() if payload.note else None,
        channel=payload.channel,
        amount=payload.amount,
        transaction_type="receipt",
        created_by=context.actor,
    )
    session.add(payment)
    session.flush()
    for item in allocations:
        assignment_id = item["requirement_assignment_id"]
        if assignment_id:
            assignment = session.get(StudentRequirement, assignment_id)
            requirement = (
                session.get(Requirement, assignment.requirement_id) if assignment else None
            )
            if assignment and requirement and not requirement.is_mandatory:
                charge_reference = f"REQ:{assignment.id}"
                charged = session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.student_id == student.id,
                        LedgerEntry.reference == charge_reference,
                    )
                )
                if not charged:
                    session.add(
                        LedgerEntry(
                            id=uuid.uuid4(),
                            school_id=context.school_id,
                            period_id=period.id,
                            student_id=student.id,
                            entry_type="requirement_charge",
                            amount=assignment.expected_amount,
                            reference=charge_reference,
                            requirement_assignment_id=assignment.id,
                        )
                    )
        session.add(
            PaymentAllocation(
                id=uuid.uuid4(),
                payment_id=payment.id,
                student_id=student.id,
                requirement_assignment_id=assignment_id,
                allocation_type=item["allocation_type"],
                amount=item["amount"],
            )
        )
    session.add(
        LedgerEntry(
            id=uuid.uuid4(),
            school_id=context.school_id,
            period_id=period.id,
            student_id=student.id,
            entry_type="payment",
            amount=-payload.amount,
            reference=reference,
            description="Learner payment received",
            payment_id=payment.id,
        )
    )
    commitment = hashlib.sha256(
        f"{payment.id}|{payload.amount}|UGX|{reference}".encode()
    ).hexdigest()
    session.add(
        StellarAnchor(
            id=uuid.uuid4(), payment_id=payment.id, commitment_hash=commitment, status="pending"
        )
    )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="payment",
            entity_id=payment.id,
            action="created",
            actor=context.actor,
            summary=f"Recorded {payment.amount} {payment.currency} via {payment.channel}",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This payment reference has already been recorded"
        ) from error
    return _payment_summary(session, payment)


@router.post("/payments/{payment_id}/corrections", response_model=PaymentSummary)
def correct_payment(
    payment_id: uuid.UUID,
    payload: PaymentCorrectionCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    if context.role not in {"owner", "bursar"}:
        raise HTTPException(status_code=403, detail="Only an owner or bursar can correct receipts")
    original = session.scalar(
        select(Payment)
        .where(Payment.id == payment_id, Payment.school_id == context.school_id)
        .with_for_update()
    )
    if original is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if original.transaction_type != "receipt":
        raise HTTPException(status_code=409, detail="Correction records cannot be corrected")
    prior = session.scalar(
        select(Payment).where(
            Payment.original_payment_id == original.id,
            Payment.idempotency_key == payload.idempotency_key,
        )
    )
    if prior is not None:
        return _payment_summary(session, prior)
    resolve_period(
        session, school_id=context.school_id, period_id=original.period_id, writable=True
    )
    corrected = -(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.original_payment_id == original.id,
                Payment.transaction_type.in_(("reversal", "refund")),
            )
        )
        or Decimal("0")
    )
    remaining = original.amount - corrected
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="This receipt is already fully corrected")
    if payload.action == "reverse":
        if corrected:
            raise HTTPException(
                status_code=409,
                detail="A partially refunded receipt cannot be reversed",
            )
        correction_amount = original.amount
        transaction_type = "reversal"
    else:
        correction_amount = payload.amount or Decimal("0")
        if correction_amount <= 0 or correction_amount > remaining:
            raise HTTPException(
                status_code=422,
                detail=f"Refund cannot exceed UGX {remaining:,.2f}",
            )
        transaction_type = "refund"
    original_allocations = session.scalars(
        select(PaymentAllocation)
        .where(PaymentAllocation.payment_id == original.id)
        .order_by(PaymentAllocation.id.desc())
    ).all()
    corrections = session.execute(
        select(PaymentAllocation, Payment)
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(Payment.original_payment_id == original.id)
    ).all()
    already_by_target: dict[tuple[str, uuid.UUID | None], Decimal] = {}
    for allocation, _payment in corrections:
        key = (allocation.allocation_type, allocation.requirement_assignment_id)
        already_by_target[key] = already_by_target.get(key, Decimal("0")) - allocation.amount
    remaining_refund = correction_amount
    correction_allocations = []
    for allocation in original_allocations:
        key = (allocation.allocation_type, allocation.requirement_assignment_id)
        available = allocation.amount - already_by_target.get(key, Decimal("0"))
        take = min(available, remaining_refund)
        if take > 0:
            correction_allocations.append((allocation, take))
            remaining_refund -= take
        if remaining_refund == 0:
            break
    if remaining_refund:
        raise HTTPException(status_code=409, detail="Original allocation evidence is incomplete")
    correction = Payment(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=original.period_id,
        receipt_no=_next_payment_receipt(session, context.school_id),
        external_reference=(
            f"{transaction_type[:3].upper()}-{original.id.hex[:16].upper()}-"
            f"{uuid.uuid4().hex[:6].upper()}"
        ),
        payer_name=original.payer_name,
        note=f"{transaction_type.title()} of {original.receipt_no}",
        channel=original.channel,
        amount=-correction_amount,
        currency=original.currency,
        status="reconciled",
        transaction_type=transaction_type,
        original_payment_id=original.id,
        correction_reason=payload.reason.strip(),
        idempotency_key=payload.idempotency_key,
        created_by=context.actor,
    )
    session.add(correction)
    session.flush()
    student_id = original_allocations[0].student_id
    for allocation, amount in correction_allocations:
        session.add(
            PaymentAllocation(
                id=uuid.uuid4(),
                payment_id=correction.id,
                student_id=allocation.student_id,
                requirement_assignment_id=allocation.requirement_assignment_id,
                allocation_type=allocation.allocation_type,
                amount=-amount,
            )
        )
    session.add_all(
        [
            LedgerEntry(
                id=uuid.uuid4(),
                school_id=context.school_id,
                period_id=original.period_id,
                student_id=student_id,
                entry_type=transaction_type,
                amount=correction_amount,
                reference=correction.external_reference,
                description=f"{transaction_type.title()} of {original.receipt_no}",
                payment_id=correction.id,
            ),
            StellarAnchor(
                id=uuid.uuid4(),
                payment_id=correction.id,
                commitment_hash=hashlib.sha256(
                    f"{correction.id}|{-correction_amount}|UGX|{correction.external_reference}".encode()
                ).hexdigest(),
                status="pending",
            ),
        ]
    )
    total_corrected = corrected + correction_amount
    original.status = (
        "reversed"
        if transaction_type == "reversal"
        else "refunded"
        if total_corrected == original.amount
        else "partially_refunded"
    )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="payment",
            entity_id=original.id,
            action=transaction_type,
            actor=context.actor,
            summary=(
                f"Posted {transaction_type} {correction.receipt_no} for {original.receipt_no}: "
                f"{payload.reason.strip()}"
            ),
        )
    )
    session.commit()
    return _payment_summary(session, correction)


@router.post("/payments/{payment_id}/reissues")
def reissue_payment_receipt(
    payment_id: uuid.UUID,
    payload: ReceiptReissueCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    payment = session.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == context.school_id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    record = PaymentReceiptReissue(
        school_id=context.school_id,
        payment_id=payment.id,
        reason=payload.reason.strip(),
        reissued_by=context.actor,
    )
    session.add(record)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="payment_receipt",
            entity_id=record.id,
            action="reissued",
            actor=context.actor,
            summary=f"Reissued {payment.receipt_no}: {record.reason}",
        )
    )
    session.commit()
    return {"receipt_no": payment.receipt_no, "reissue_id": record.id}


@router.get("/payments/{payment_id}/receipt", response_model=ReceiptDetail)
def get_payment_receipt(
    payment_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    payment = session.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == context.school_id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    school = session.get(School, payment.school_id)
    summary = _payment_summary(session, payment).model_dump()
    first = session.scalar(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    )
    student_id = first.student_id
    period = resolve_period(session, school_id=context.school_id, period_id=payment.period_id)
    totals = load_student_financial_totals(session, period=period, student_id=student_id)
    original = (
        session.get(Payment, payment.original_payment_id) if payment.original_payment_id else None
    )
    correction_base = original.id if original else payment.id
    corrected_total = -(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.original_payment_id == correction_base
            )
        )
        or Decimal("0")
    )
    reissue_count = (
        session.scalar(
            select(func.count(PaymentReceiptReissue.id)).where(
                PaymentReceiptReissue.payment_id == payment.id
            )
        )
        or 0
    )
    return ReceiptDetail(
        **summary,
        school_name=school.name,
        school_district=school.district,
        payer_name=payment.payer_name,
        note=payment.note,
        billed=totals.net_assessed,
        paid_to_date=max(totals.net_collected, Decimal("0")),
        balance=totals.closing_balance,
        reissue_count=reissue_count,
        original_receipt_no=original.receipt_no if original else None,
        corrected_total=corrected_total,
    )
