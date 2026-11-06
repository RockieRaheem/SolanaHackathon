import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AcademicClass,
    AuditEvent,
    BillingAdjustment,
    BillingPublication,
    Enrollment,
    FeeCategory,
    FeeStructure,
    LedgerEntry,
    Person,
    Requirement,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import BillingAdjustmentCreate, BillingPublishCreate

router = APIRouter(prefix="/api/v1", tags=["billing"])
PAYABLE_REQUIREMENT_TYPES = {"payment", "school_item"}
CREDIT_TYPES = {"discount", "sponsorship_credit", "waiver"}


def assign_published_general_fee(
    session: Session,
    *,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    student_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: str,
) -> dict:
    """Post the published whole-class fee when a learner receives a placement.

    Draft plans remain subject to the normal preview/publication control. A learner
    who already has a different fee assignment in the period is never charged a
    second time automatically; that movement is returned for bursar review.
    """
    plan = session.scalar(
        select(FeeStructure).where(
            FeeStructure.school_id == school_id,
            FeeStructure.period_id == period_id,
            FeeStructure.class_id == class_id,
            FeeStructure.target_type == "cohort",
            FeeStructure.stream_id.is_(None),
            FeeStructure.boarding_status.is_(None),
            FeeStructure.status == "published",
            FeeStructure.is_active.is_(True),
        )
    )
    if plan is None:
        draft_exists = session.scalar(
            select(FeeStructure.id).where(
                FeeStructure.school_id == school_id,
                FeeStructure.period_id == period_id,
                FeeStructure.class_id == class_id,
                FeeStructure.target_type == "cohort",
                FeeStructure.stream_id.is_(None),
                FeeStructure.boarding_status.is_(None),
                FeeStructure.status == "draft",
                FeeStructure.is_active.is_(True),
            )
        )
        return {"status": "pending_publication" if draft_exists else "not_configured"}

    assignments = session.execute(
        select(StudentFeeAssignment, FeeStructure)
        .join(FeeStructure, FeeStructure.id == StudentFeeAssignment.fee_structure_id)
        .where(
            StudentFeeAssignment.student_id == student_id,
            FeeStructure.school_id == school_id,
            FeeStructure.period_id == period_id,
        )
    ).all()
    if any(assignment.fee_structure_id == plan.id for assignment, _ in assignments):
        return {"status": "already_assigned", "plan_id": str(plan.id)}
    if assignments:
        return {
            "status": "review_required",
            "plan_id": str(plan.id),
            "message": (
                "The learner already has a fee posted in this period. Placement was saved, "
                "but the new class fee was not added automatically. Review the account first."
            ),
        }

    idempotency_key = f"auto_fee_{student_id.hex}_{plan.id.hex}"
    preview_token = hashlib.sha256(idempotency_key.encode()).hexdigest()
    publication = session.scalar(
        select(BillingPublication).where(
            BillingPublication.school_id == school_id,
            BillingPublication.period_id == period_id,
            BillingPublication.idempotency_key == idempotency_key,
        )
    )
    if publication is None:
        publication = BillingPublication(
            school_id=school_id,
            period_id=period_id,
            idempotency_key=idempotency_key,
            preview_token=preview_token,
            learner_count=1,
            charge_total=plan.total_amount,
            credit_total=Decimal("0"),
            net_total=plan.total_amount,
            created_by=actor,
        )
        session.add(publication)
        session.flush()

    assignment = StudentFeeAssignment(
        student_id=student_id,
        fee_structure_id=plan.id,
        publication_id=publication.id,
        amount=plan.total_amount,
    )
    session.add(assignment)
    session.flush()
    session.add(
        LedgerEntry(
            school_id=school_id,
            period_id=period_id,
            student_id=student_id,
            entry_type="fee_charge",
            amount=plan.total_amount,
            currency=plan.currency,
            reference=f"FEE:{assignment.id}",
            description=plan.name,
            publication_id=publication.id,
            fee_assignment_id=assignment.id,
        )
    )
    session.add(
        AuditEvent(
            school_id=school_id,
            entity_type="student_fee_assignment",
            entity_id=assignment.id,
            action="automatically_assigned",
            actor=actor,
            summary=f"Applied published general fee {plan.name} to learner placement",
        )
    )
    return {
        "status": "assigned",
        "plan_id": str(plan.id),
        "plan_name": plan.name,
        "amount": str(plan.total_amount),
    }


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _billing_preview(session: Session, school_id: uuid.UUID, period_id: uuid.UUID) -> dict:
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    enrollment_rows = session.execute(
        select(Enrollment, Student, Person, AcademicClass)
        .join(Student, Student.id == Enrollment.student_id)
        .join(Person, Person.id == Student.person_id)
        .join(AcademicClass, AcademicClass.id == Enrollment.class_id)
        .where(
            Enrollment.period_id == period.id,
            Student.school_id == school_id,
            Student.status == "active",
        )
        .order_by(Person.last_name, Person.first_name, Student.admission_no)
    ).all()
    learners = {
        student.id: {
            "student": student,
            "enrollment": enrollment,
            "name": f"{person.first_name} {person.last_name}",
        }
        for enrollment, student, person, _academic_class in enrollment_rows
    }
    plans = session.scalars(
        select(FeeStructure)
        .where(
            FeeStructure.school_id == school_id,
            FeeStructure.period_id == period.id,
            FeeStructure.is_active.is_(True),
        )
        .options(
            selectinload(FeeStructure.selected_learners),
            selectinload(FeeStructure.items),
            selectinload(FeeStructure.installments),
        )
        .order_by(FeeStructure.name, FeeStructure.id)
    ).all()
    requirements = session.scalars(
        select(Requirement)
        .where(
            Requirement.school_id == school_id,
            Requirement.period_id == period.id,
            Requirement.is_active.is_(True),
        )
        .options(
            selectinload(Requirement.classes),
            selectinload(Requirement.selected_learners),
        )
        .order_by(Requirement.name, Requirement.id)
    ).all()
    existing_fee = set(
        session.execute(
            select(StudentFeeAssignment.student_id, StudentFeeAssignment.fee_structure_id)
            .join(FeeStructure, FeeStructure.id == StudentFeeAssignment.fee_structure_id)
            .where(FeeStructure.school_id == school_id, FeeStructure.period_id == period.id)
        ).all()
    )
    students_with_existing_fee = {student_id for student_id, _plan_id in existing_fee}
    existing_requirements = set(
        session.execute(
            select(StudentRequirement.student_id, StudentRequirement.requirement_id)
            .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
            .where(Requirement.school_id == school_id, Requirement.period_id == period.id)
        ).all()
    )

    plan_matches: dict[uuid.UUID, list[FeeStructure]] = {student_id: [] for student_id in learners}
    for plan in plans:
        selected = {item.student_id for item in plan.selected_learners}
        for student_id, row in learners.items():
            student, enrollment = row["student"], row["enrollment"]
            if enrollment.class_id != plan.class_id:
                continue
            if plan.stream_id and enrollment.stream_id != plan.stream_id:
                continue
            if plan.boarding_status and student.boarding_status != plan.boarding_status:
                continue
            if plan.target_type == "selected" and student_id not in selected:
                continue
            plan_matches[student_id].append(plan)

    conflicts = []
    exclusions = []
    fee_actions: list[tuple[Student, FeeStructure]] = []
    plan_counts: dict[uuid.UUID, int] = {plan.id: 0 for plan in plans}
    for student_id, row in learners.items():
        matches = plan_matches[student_id]
        if len(matches) > 1:
            conflicts.append(
                {
                    "student_id": str(student_id),
                    "admission_no": row["student"].admission_no,
                    "student_name": row["name"],
                    "reason": "Matches more than one fee plan",
                    "plans": [plan.name for plan in matches],
                }
            )
            continue
        if not matches:
            exclusions.append(
                {
                    "student_id": str(student_id),
                    "admission_no": row["student"].admission_no,
                    "student_name": row["name"],
                    "reason": "No fee plan matches this learner's class, stream and residence",
                }
            )
            continue
        plan = matches[0]
        if (student_id, plan.id) not in existing_fee:
            if student_id in students_with_existing_fee:
                exclusions.append(
                    {
                        "student_id": str(student_id),
                        "admission_no": row["student"].admission_no,
                        "student_name": row["name"],
                        "reason": (
                            "Existing fee assignment requires bursar review after class movement"
                        ),
                    }
                )
                continue
            fee_actions.append((row["student"], plan))
            plan_counts[plan.id] += 1

    requirement_actions: list[tuple[Student, Requirement]] = []
    requirement_counts: dict[uuid.UUID, int] = {item.id: 0 for item in requirements}
    for requirement in requirements:
        class_ids = {item.class_id for item in requirement.classes}
        selected_ids = {item.student_id for item in requirement.selected_learners}
        for student_id, row in learners.items():
            student, enrollment = row["student"], row["enrollment"]
            if enrollment.class_id not in class_ids:
                continue
            if requirement.stream_id and enrollment.stream_id != requirement.stream_id:
                continue
            if (
                requirement.boarding_status
                and student.boarding_status != requirement.boarding_status
            ):
                continue
            if selected_ids and student_id not in selected_ids:
                continue
            if not requirement.is_mandatory and student_id not in selected_ids:
                continue
            if (student_id, requirement.id) in existing_requirements:
                continue
            requirement_actions.append((student, requirement))
            requirement_counts[requirement.id] += 1

    adjustments = session.scalars(
        select(BillingAdjustment)
        .where(
            BillingAdjustment.school_id == school_id,
            BillingAdjustment.period_id == period.id,
            BillingAdjustment.status == "draft",
        )
        .order_by(BillingAdjustment.created_at, BillingAdjustment.id)
    ).all()
    adjustment_actions = [item for item in adjustments if item.student_id in learners]

    fee_total = sum((plan.total_amount for _, plan in fee_actions), Decimal("0"))
    requirement_total = sum(
        (
            requirement.amount
            for _, requirement in requirement_actions
            if requirement.requirement_type in PAYABLE_REQUIREMENT_TYPES
        ),
        Decimal("0"),
    )
    addition_total = sum(
        (item.amount for item in adjustment_actions if item.adjustment_type == "addition"),
        Decimal("0"),
    )
    credit_total = sum(
        (item.amount for item in adjustment_actions if item.adjustment_type in CREDIT_TYPES),
        Decimal("0"),
    )
    charge_total = fee_total + requirement_total + addition_total
    net_total = charge_total - credit_total
    affected_students = (
        {student.id for student, _ in fee_actions}
        | {student.id for student, _ in requirement_actions}
        | {item.student_id for item in adjustment_actions}
    )
    token_source = {
        "school_id": str(school_id),
        "period_id": str(period.id),
        "fees": sorted(
            (str(student.id), str(plan.id), _money(plan.total_amount))
            for student, plan in fee_actions
        ),
        "requirements": sorted(
            (str(student.id), str(requirement.id), _money(requirement.amount))
            for student, requirement in requirement_actions
        ),
        "adjustments": sorted(
            (str(item.id), item.adjustment_type, _money(item.amount))
            for item in adjustment_actions
        ),
        "conflicts": sorted(item["student_id"] for item in conflicts),
    }
    preview_token = hashlib.sha256(
        json.dumps(token_source, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "school_id": str(school_id),
        "period_id": str(period.id),
        "period_name": f"{period.academic_year.name} · {period.name}",
        "preview_token": preview_token,
        "can_publish": not conflicts and bool(
            fee_actions or requirement_actions or adjustment_actions
        ),
        "summary": {
            "learner_count": len(affected_students),
            "fee_assignment_count": len(fee_actions),
            "requirement_assignment_count": len(requirement_actions),
            "adjustment_count": len(adjustment_actions),
            "charge_total": _money(charge_total),
            "credit_total": _money(credit_total),
            "net_total": _money(net_total),
        },
        "fee_plans": [
            {
                "id": str(plan.id),
                "name": plan.name,
                "learner_count": plan_counts[plan.id],
                "amount_per_learner": _money(plan.total_amount),
                "total": _money(plan.total_amount * plan_counts[plan.id]),
            }
            for plan in plans
            if plan_counts[plan.id]
        ],
        "requirements": [
            {
                "id": str(requirement.id),
                "name": requirement.name,
                "type": requirement.requirement_type,
                "learner_count": requirement_counts[requirement.id],
                "amount_per_learner": _money(requirement.amount),
                "total": _money(requirement.amount * requirement_counts[requirement.id]),
            }
            for requirement in requirements
            if requirement_counts[requirement.id]
        ],
        "adjustments": [
            {
                "id": str(item.id),
                "student_id": str(item.student_id),
                "student_name": learners[item.student_id]["name"],
                "type": item.adjustment_type,
                "description": item.description,
                "amount": _money(item.amount),
            }
            for item in adjustment_actions
        ],
        "conflicts": conflicts,
        "exclusions": exclusions,
        "_actions": {
            "fees": fee_actions,
            "requirements": requirement_actions,
            "adjustments": adjustment_actions,
        },
    }


def _public_preview(preview: dict) -> dict:
    return {key: value for key, value in preview.items() if key != "_actions"}


def _publication_result(publication: BillingPublication, *, replayed: bool) -> dict:
    return {
        "id": publication.id,
        "status": publication.status,
        "replayed": replayed,
        "learner_count": publication.learner_count,
        "charge_total": publication.charge_total,
        "credit_total": publication.credit_total,
        "net_total": publication.net_total,
        "created_at": publication.created_at,
    }


@router.get("/billing/preview")
def preview_billing(
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
) -> dict:
    context.assert_school(school_id)
    return _public_preview(_billing_preview(session, school_id, period_id))


@router.post("/billing/publish", status_code=status.HTTP_201_CREATED)
def publish_billing(
    payload: BillingPublishCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> dict:
    context.assert_school(payload.school_id)
    resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        writable=True,
    )
    existing = session.scalar(
        select(BillingPublication).where(
            BillingPublication.school_id == context.school_id,
            BillingPublication.period_id == payload.period_id,
            BillingPublication.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.preview_token != payload.preview_token:
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used for a different billing preview",
            )
        return _publication_result(existing, replayed=True)

    preview = _billing_preview(session, context.school_id, payload.period_id)
    if preview["preview_token"] != payload.preview_token:
        raise HTTPException(
            status_code=409,
            detail="Billing configuration changed after preview; review the updated totals",
        )
    if preview["conflicts"]:
        raise HTTPException(status_code=409, detail="Resolve fee plan conflicts before publishing")
    if not preview["can_publish"]:
        raise HTTPException(status_code=409, detail="There are no new learner bills to publish")

    summary = preview["summary"]
    publication = BillingPublication(
        school_id=context.school_id,
        period_id=payload.period_id,
        idempotency_key=payload.idempotency_key,
        preview_token=payload.preview_token,
        learner_count=summary["learner_count"],
        charge_total=Decimal(summary["charge_total"]),
        credit_total=Decimal(summary["credit_total"]),
        net_total=Decimal(summary["net_total"]),
        created_by=context.actor,
    )
    session.add(publication)
    session.flush()
    now = datetime.now(UTC)
    for student, plan in preview["_actions"]["fees"]:
        assignment = StudentFeeAssignment(
            student_id=student.id,
            fee_structure_id=plan.id,
            publication_id=publication.id,
            amount=plan.total_amount,
        )
        session.add(assignment)
        session.flush()
        session.add(
            LedgerEntry(
                school_id=context.school_id,
                period_id=payload.period_id,
                student_id=student.id,
                entry_type="fee_charge",
                amount=plan.total_amount,
                currency=plan.currency,
                reference=f"FEE:{assignment.id}",
                description=plan.name,
                publication_id=publication.id,
                fee_assignment_id=assignment.id,
            )
        )
        plan.status = "published"
        plan.published_at = plan.published_at or now

    for student, requirement in preview["_actions"]["requirements"]:
        assignment = StudentRequirement(
            requirement_id=requirement.id,
            student_id=student.id,
            publication_id=publication.id,
            expected_amount=requirement.amount,
            expected_quantity=requirement.quantity,
        )
        session.add(assignment)
        session.flush()
        if requirement.requirement_type in PAYABLE_REQUIREMENT_TYPES:
            session.add(
                LedgerEntry(
                    school_id=context.school_id,
                    period_id=payload.period_id,
                    student_id=student.id,
                    entry_type="requirement_charge",
                    amount=requirement.amount,
                    reference=f"REQ:{assignment.id}",
                    description=requirement.name,
                    publication_id=publication.id,
                    requirement_assignment_id=assignment.id,
                )
            )
        requirement.status = "published"

    for adjustment in preview["_actions"]["adjustments"]:
        signed_amount = (
            -adjustment.amount if adjustment.adjustment_type in CREDIT_TYPES else adjustment.amount
        )
        session.add(
            LedgerEntry(
                school_id=context.school_id,
                period_id=payload.period_id,
                student_id=adjustment.student_id,
                entry_type=adjustment.adjustment_type,
                amount=signed_amount,
                reference=f"ADJ:{adjustment.id}",
                description=adjustment.description,
                publication_id=publication.id,
                billing_adjustment_id=adjustment.id,
            )
        )
        adjustment.status = "published"
        adjustment.publication_id = publication.id

    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="billing_publication",
            entity_id=publication.id,
            action="published",
            actor=context.actor,
            summary=(
                f"Published bills for {publication.learner_count} learners totaling "
                f"{publication.net_total} UGX"
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        replay = session.scalar(
            select(BillingPublication).where(
                BillingPublication.school_id == context.school_id,
                BillingPublication.period_id == payload.period_id,
                BillingPublication.idempotency_key == payload.idempotency_key,
            )
        )
        if replay and replay.preview_token == payload.preview_token:
            return _publication_result(replay, replayed=True)
        raise HTTPException(
            status_code=409,
            detail="Billing was changed concurrently; preview again before publishing",
        ) from error
    session.refresh(publication)
    return _publication_result(publication, replayed=False)


@router.get("/billing/adjustments")
def list_adjustments(
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
) -> list[dict]:
    context.assert_school(school_id)
    resolve_period(session, school_id=school_id, period_id=period_id)
    rows = session.execute(
        select(BillingAdjustment, Student, Person, FeeCategory)
        .join(Student, Student.id == BillingAdjustment.student_id)
        .join(Person, Person.id == Student.person_id)
        .outerjoin(FeeCategory, FeeCategory.id == BillingAdjustment.category_id)
        .where(
            BillingAdjustment.school_id == school_id,
            BillingAdjustment.period_id == period_id,
        )
        .order_by(BillingAdjustment.created_at.desc())
    ).all()
    return [
        {
            "id": adjustment.id,
            "student_id": student.id,
            "student_name": f"{person.first_name} {person.last_name}",
            "admission_no": student.admission_no,
            "category_name": category.name if category else None,
            "adjustment_type": adjustment.adjustment_type,
            "amount": adjustment.amount,
            "description": adjustment.description,
            "reason": adjustment.reason,
            "status": adjustment.status,
            "created_at": adjustment.created_at,
        }
        for adjustment, student, person, category in rows
    ]


@router.post("/billing/adjustments", status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: BillingAdjustmentCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> dict:
    context.assert_school(payload.school_id)
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        writable=True,
    )
    student = session.scalar(
        select(Student)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Student.id == payload.student_id,
            Student.school_id == context.school_id,
            Student.status == "active",
            Enrollment.period_id == period.id,
        )
    )
    if student is None:
        raise HTTPException(status_code=422, detail="Learner is not active in this period")
    if payload.category_id:
        category = session.scalar(
            select(FeeCategory).where(
                FeeCategory.id == payload.category_id,
                FeeCategory.school_id == context.school_id,
            )
        )
        if category is None:
            raise HTTPException(status_code=422, detail="Fee category is invalid")
    if payload.adjustment_type == "sponsorship_credit":
        posted_balance = session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0"))).where(
                LedgerEntry.school_id == context.school_id,
                LedgerEntry.period_id == period.id,
                LedgerEntry.student_id == student.id,
            )
        )
        draft_credits = session.scalar(
            select(func.coalesce(func.sum(BillingAdjustment.amount), Decimal("0"))).where(
                BillingAdjustment.school_id == context.school_id,
                BillingAdjustment.period_id == period.id,
                BillingAdjustment.student_id == student.id,
                BillingAdjustment.status == "draft",
                BillingAdjustment.adjustment_type.in_(CREDIT_TYPES),
            )
        )
        available_balance = max(Decimal("0"), posted_balance - draft_credits)
        if available_balance <= 0:
            raise HTTPException(
                status_code=422,
                detail="Apply or publish the learner's class fee before recording a scholarship.",
            )
        if payload.amount > available_balance:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Scholarship cannot exceed the learner's available balance of "
                    f"{_money(available_balance)} UGX."
                ),
            )
    adjustment = BillingAdjustment(
        **payload.model_dump(exclude={"period_id", "school_id"}),
        school_id=context.school_id,
        period_id=period.id,
    )
    session.add(adjustment)
    session.flush()
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="billing_adjustment",
            entity_id=adjustment.id,
            action="created",
            actor=context.actor,
            summary=f"Created draft {adjustment.adjustment_type}: {adjustment.description}",
        )
    )
    session.commit()
    return {"id": adjustment.id, "status": adjustment.status}


@router.delete("/billing/adjustments/{adjustment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adjustment(
    adjustment_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> None:
    adjustment = session.scalar(
        select(BillingAdjustment).where(
            BillingAdjustment.id == adjustment_id,
            BillingAdjustment.school_id == context.school_id,
        )
    )
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Billing adjustment not found")
    if adjustment.status != "draft":
        raise HTTPException(status_code=409, detail="Published adjustments are immutable")
    resolve_period(
        session,
        school_id=context.school_id,
        period_id=adjustment.period_id,
        writable=True,
    )
    session.execute(delete(BillingAdjustment).where(BillingAdjustment.id == adjustment.id))
    session.commit()
