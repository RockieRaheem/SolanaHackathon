import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AcademicClass,
    AuditEvent,
    Enrollment,
    PaymentAllocation,
    Person,
    Requirement,
    RequirementClass,
    RequirementLearner,
    School,
    Stream,
    Student,
    StudentRequirement,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import RequirementCreate, RequirementFulfilmentCreate

router = APIRouter(prefix="/api/v1", tags=["requirements"])


def requirement_status(
    assignment: StudentRequirement, requirement: Requirement, paid: Decimal
) -> str:
    if assignment.is_waived:
        return "waived"
    fulfilled = assignment.fulfilled_quantity
    if requirement.requirement_type == "payment":
        if paid >= assignment.expected_amount:
            return "complete"
        return "partially_paid" if paid > 0 else "unpaid"
    if requirement.requirement_type == "school_item":
        if paid < assignment.expected_amount:
            return "partially_paid" if paid > 0 else "unpaid"
        if fulfilled >= assignment.expected_quantity:
            return "issued"
        return "partially_issued" if fulfilled > 0 else "paid"
    if fulfilled >= assignment.expected_quantity:
        return "received"
    return "partially_received" if fulfilled > 0 else "pending"


def _paid_subquery():
    return (
        select(
            PaymentAllocation.requirement_assignment_id.label("assignment_id"),
            func.sum(PaymentAllocation.amount).label("paid"),
        )
        .where(PaymentAllocation.requirement_assignment_id.is_not(None))
        .group_by(PaymentAllocation.requirement_assignment_id)
        .subquery()
    )


@router.post("/requirements", status_code=status.HTTP_201_CREATED)
def create_requirement(
    payload: RequirementCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> dict:
    context.assert_school(payload.school_id)
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        academic_year=payload.academic_year,
        term=payload.term,
        writable=True,
    )
    if session.get(School, payload.school_id) is None:
        raise HTTPException(status_code=404, detail="School not found")
    classes = session.scalars(
        select(AcademicClass).where(AcademicClass.id.in_(payload.class_ids))
    ).all()
    if len(classes) != len(payload.class_ids) or any(
        item.school_id != payload.school_id for item in classes
    ):
        raise HTTPException(status_code=422, detail="One or more classes are invalid")
    stream = session.get(Stream, payload.stream_id) if payload.stream_id else None
    if stream is not None and stream.class_id not in payload.class_ids:
        raise HTTPException(status_code=422, detail="Stream does not belong to a target class")
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
                    Enrollment.class_id.in_(payload.class_ids),
                )
            ).all()
        )
        if eligible_ids != set(payload.student_ids):
            raise HTTPException(
                status_code=422,
                detail="Every selected learner must be active in a target class and period",
            )

    requirement = Requirement(
        id=uuid.uuid4(),
        **payload.model_dump(
            exclude={
                "class_ids",
                "student_ids",
                "code",
                "period_id",
                "academic_year",
                "term",
            }
        ),
        period_id=period.id,
        academic_year=period.academic_year.year,
        term=period.sequence,
        code=payload.code.upper(),
    )
    requirement.classes = [RequirementClass(class_id=class_id) for class_id in payload.class_ids]
    requirement.selected_learners = [
        RequirementLearner(student_id=student_id) for student_id in payload.student_ids
    ]
    session.add(requirement)
    session.flush()
    session.add(
        AuditEvent(
            school_id=payload.school_id,
            entity_type="requirement",
            entity_id=requirement.id,
            action="created",
            actor=context.actor,
            summary=f"Created draft requirement {requirement.name}",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A requirement with this code already exists for the selected term",
        ) from error
    return {"id": requirement.id, "assigned_count": 0, "status": "draft"}


@router.get("/requirements")
def list_requirements(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
) -> list[dict]:
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    requirements = session.scalars(
        select(Requirement)
        .where(
            Requirement.school_id == school_id,
            Requirement.period_id == period.id,
            Requirement.is_active.is_(True),
        )
        .options(
            selectinload(Requirement.classes).selectinload(RequirementClass.academic_class),
            selectinload(Requirement.assignments),
            selectinload(Requirement.selected_learners),
        )
        .order_by(Requirement.academic_year.desc(), Requirement.term.desc(), Requirement.name)
    ).all()
    paid_rows = dict(
        session.execute(
            select(
                PaymentAllocation.requirement_assignment_id,
                func.coalesce(func.sum(PaymentAllocation.amount), 0),
            )
            .where(PaymentAllocation.requirement_assignment_id.is_not(None))
            .group_by(PaymentAllocation.requirement_assignment_id)
        ).all()
    )
    result = []
    for requirement in requirements:
        statuses = [
            requirement_status(item, requirement, paid_rows.get(item.id, Decimal("0")))
            for item in requirement.assignments
        ]
        complete_states = {"complete", "issued", "received", "waived"}
        result.append(
            {
                "id": requirement.id,
                "name": requirement.name,
                "code": requirement.code,
                "requirement_type": requirement.requirement_type,
                "description": requirement.description,
                "academic_year": requirement.academic_year,
                "term": requirement.term,
                "amount": requirement.amount,
                "quantity": requirement.quantity,
                "unit": requirement.unit,
                "due_date": requirement.due_date,
                "is_mandatory": requirement.is_mandatory,
                "status": requirement.status,
                "stream_id": requirement.stream_id,
                "boarding_status": requirement.boarding_status,
                "selected_learner_count": len(requirement.selected_learners),
                "classes": [
                    {"id": item.class_id, "name": item.academic_class.name}
                    for item in requirement.classes
                ],
                "assigned_count": len(requirement.assignments),
                "completed_count": sum(item in complete_states for item in statuses),
                "paid_amount": sum(
                    (paid_rows.get(item.id, Decimal("0")) for item in requirement.assignments),
                    Decimal("0"),
                ),
            }
        )
    return result


@router.delete("/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_requirement(
    requirement_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> Response:
    requirement = session.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id,
            Requirement.school_id == context.school_id,
            Requirement.is_active.is_(True),
        )
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    resolve_period(
        session,
        school_id=context.school_id,
        period_id=requirement.period_id,
        writable=True,
    )
    assignment_count = session.scalar(
        select(func.count(StudentRequirement.id)).where(
            StudentRequirement.requirement_id == requirement.id
        )
    )
    if requirement.status != "draft" or assignment_count:
        raise HTTPException(status_code=409, detail="Published requirements cannot be removed")
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="requirement",
            entity_id=requirement.id,
            action="deleted",
            actor=context.actor,
            summary=f"Deleted draft requirement {requirement.name}",
        )
    )
    session.delete(requirement)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/requirements/{requirement_id}/sync")
def sync_requirement(
    requirement_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> dict:
    requirement = session.scalar(
        select(Requirement)
        .where(Requirement.id == requirement_id, Requirement.school_id == context.school_id)
        .options(selectinload(Requirement.classes))
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    raise HTTPException(
        status_code=409,
        detail="Use billing preview and publication to assign requirements safely",
    )


@router.get("/requirement-assignments")
def list_requirement_assignments(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    requirement_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    assignment_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:read")),
) -> list[dict]:
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    paid = _paid_subquery()
    statement = (
        select(StudentRequirement, Requirement, Student, Person, paid.c.paid, AcademicClass)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .join(Student, Student.id == StudentRequirement.student_id)
        .join(Person, Person.id == Student.person_id)
        .outerjoin(paid, paid.c.assignment_id == StudentRequirement.id)
        .outerjoin(
            Enrollment,
            and_(
                Enrollment.student_id == Student.id,
                Enrollment.period_id == Requirement.period_id,
            ),
        )
        .outerjoin(AcademicClass, AcademicClass.id == Enrollment.class_id)
        .where(Requirement.school_id == school_id, Requirement.period_id == period.id)
        .order_by(Person.last_name, Person.first_name, Requirement.name)
    )
    if requirement_id:
        statement = statement.where(Requirement.id == requirement_id)
    if student_id:
        statement = statement.where(Student.id == student_id)
    rows = session.execute(statement).all()
    items = []
    for assignment, requirement, student, person, paid_value, academic_class in rows:
        paid_amount = paid_value or Decimal("0")
        current_status = requirement_status(assignment, requirement, paid_amount)
        if assignment_status and current_status != assignment_status:
            continue
        items.append(
            {
                "id": assignment.id,
                "student_id": student.id,
                "student_name": f"{person.first_name} {person.last_name}",
                "admission_no": student.admission_no,
                "class_name": academic_class.name if academic_class else "Unplaced",
                "requirement_id": requirement.id,
                "requirement_name": requirement.name,
                "requirement_type": requirement.requirement_type,
                "expected_amount": assignment.expected_amount,
                "paid_amount": paid_amount,
                "outstanding_amount": max(assignment.expected_amount - paid_amount, Decimal("0")),
                "expected_quantity": assignment.expected_quantity,
                "fulfilled_quantity": assignment.fulfilled_quantity,
                "unit": requirement.unit,
                "status": current_status,
                "due_date": requirement.due_date,
                "is_mandatory": requirement.is_mandatory,
            }
        )
    return items


@router.post("/requirement-assignments/{assignment_id}/fulfil")
def fulfil_requirement(
    assignment_id: uuid.UUID,
    payload: RequirementFulfilmentCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("fees:write")),
) -> dict:
    assignment = session.scalar(
        select(StudentRequirement)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(
            StudentRequirement.id == assignment_id,
            Requirement.school_id == context.school_id,
        )
        .options(selectinload(StudentRequirement.requirement))
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Learner requirement not found")
    requirement = assignment.requirement
    resolve_period(
        session,
        school_id=context.school_id,
        period_id=requirement.period_id,
        writable=True,
    )
    if requirement.requirement_type == "payment":
        raise HTTPException(status_code=422, detail="This requirement is completed by payment")
    paid = session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
            PaymentAllocation.requirement_assignment_id == assignment.id
        )
    )
    if requirement.requirement_type == "school_item" and paid < assignment.expected_amount:
        raise HTTPException(
            status_code=409, detail="Record full payment before issuing this school item"
        )
    new_quantity = assignment.fulfilled_quantity + payload.quantity
    if new_quantity > assignment.expected_quantity:
        raise HTTPException(status_code=422, detail="Quantity exceeds the learner requirement")
    assignment.fulfilled_quantity = new_quantity
    assignment.fulfilment_note = payload.note.strip() if payload.note else None
    if new_quantity == assignment.expected_quantity:
        assignment.fulfilled_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=requirement.school_id,
            entity_type="student_requirement",
            entity_id=assignment.id,
            action="fulfilled",
            actor=context.actor,
            summary=f"Recorded {payload.quantity} {requirement.unit} for {requirement.name}",
        )
    )
    session.commit()
    return {
        "id": assignment.id,
        "status": requirement_status(assignment, requirement, paid),
        "fulfilled_quantity": assignment.fulfilled_quantity,
    }
