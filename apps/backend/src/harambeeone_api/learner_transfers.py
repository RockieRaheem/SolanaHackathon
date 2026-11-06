import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.billing import assign_published_general_fee
from harambeeone_api.database import get_session
from harambeeone_api.integrations import deliver_outbox_events, enqueue_integration_event
from harambeeone_api.models import (
    AcademicClass,
    AuditEvent,
    Enrollment,
    GuardianLink,
    LearnerIdentity,
    LearnerTransferCase,
    Person,
    School,
    Stream,
    Student,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import LearnerTransferCreate, LearnerTransferDecision

router = APIRouter(prefix="/api/v1", tags=["learner transfers"])


def _case_payload(case: LearnerTransferCase, session: Session, school_id: uuid.UUID) -> dict:
    source = session.get(School, case.source_school_id)
    target = session.get(School, case.target_school_id)
    return {
        "id": case.id,
        "reference": case.reference,
        "direction": "outgoing" if case.source_school_id == school_id else "incoming",
        "source_school": source.unit_name if source else "Source section",
        "target_school": target.unit_name if target else "Target section",
        "source_student_id": case.source_student_id,
        "target_student_id": case.target_student_id,
        "learner_name": " ".join(
            part
            for part in (
                case.learner_first_name,
                case.learner_middle_name,
                case.learner_last_name,
            )
            if part
        ),
        "learner_gender": case.learner_gender,
        "learner_date_of_birth": case.learner_date_of_birth,
        "learner_identification_number": case.learner_identification_number,
        "guardian_name": f"{case.guardian_first_name} {case.guardian_last_name}",
        "guardian_relationship": case.guardian_relationship,
        "guardian_phone": case.guardian_phone,
        "guardian_email": case.guardian_email,
        "purpose": case.purpose,
        "consent_method": case.consent_method,
        "consent_reference": case.consent_reference,
        "consent_recorded_at": case.consent_recorded_at,
        "status": case.status,
        "decision_reason": case.decision_reason,
        "created_at": case.created_at,
        "decided_at": case.decided_at,
    }


@router.get("/learner-transfers/context")
def transfer_context(
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
):
    school = session.get(School, context.school_id)
    if school is None or school.organization_id is None:
        return {"target_units": [], "learners": []}
    targets = session.scalars(
        select(School)
        .where(
            School.organization_id == school.organization_id,
            School.id != school.id,
        )
        .order_by(School.unit_name)
    ).all()
    learners = session.scalars(
        select(Student)
        .where(Student.school_id == context.school_id, Student.status == "active")
        .options(
            selectinload(Student.person),
            selectinload(Student.guardians).selectinload(GuardianLink.person),
        )
        .order_by(Student.admission_no)
    ).all()
    return {
        "target_units": [
            {"id": row.id, "name": row.name, "unit_name": row.unit_name} for row in targets
        ],
        "learners": [
            {
                "id": learner.id,
                "admission_no": learner.admission_no,
                "name": " ".join(
                    part
                    for part in (
                        learner.person.first_name,
                        learner.person.middle_name,
                        learner.person.last_name,
                    )
                    if part
                ),
                "guardians": [
                    {
                        "id": link.id,
                        "name": f"{link.person.first_name} {link.person.last_name}",
                        "relationship": link.relationship,
                        "is_primary": link.is_primary,
                    }
                    for link in learner.guardians
                ],
            }
            for learner in learners
        ],
    }


@router.get("/learner-transfers")
def list_transfers(
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
):
    cases = session.scalars(
        select(LearnerTransferCase)
        .where(
            or_(
                LearnerTransferCase.source_school_id == context.school_id,
                LearnerTransferCase.target_school_id == context.school_id,
            )
        )
        .order_by(LearnerTransferCase.created_at.desc())
    ).all()
    return [_case_payload(case, session, context.school_id) for case in cases]


@router.post("/learner-transfers", status_code=201)
def create_transfer(
    payload: LearnerTransferCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
):
    source_school = session.get(School, context.school_id)
    target_school = session.get(School, payload.target_school_id)
    if (
        source_school is None
        or target_school is None
        or source_school.organization_id is None
        or target_school.organization_id != source_school.organization_id
        or target_school.id == source_school.id
    ):
        raise HTTPException(
            status_code=422, detail="Target must be another section of this institution"
        )
    student = session.scalar(
        select(Student)
        .where(Student.id == payload.student_id, Student.school_id == context.school_id)
        .options(selectinload(Student.person))
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    if student.status != "active":
        raise HTTPException(status_code=409, detail="Only an active learner can be transferred")
    guardian = session.scalar(
        select(GuardianLink)
        .where(
            GuardianLink.id == payload.guardian_link_id,
            GuardianLink.student_id == student.id,
        )
        .options(selectinload(GuardianLink.person))
    )
    if guardian is None:
        raise HTTPException(status_code=422, detail="Guardian does not belong to this learner")
    pending = session.scalar(
        select(LearnerTransferCase.id).where(
            LearnerTransferCase.source_student_id == student.id,
            LearnerTransferCase.target_school_id == target_school.id,
            LearnerTransferCase.status == "pending",
        )
    )
    if pending:
        raise HTTPException(status_code=409, detail="A pending transfer already exists")
    if student.learner_identity_id is None:
        identity = LearnerIdentity(organization_id=source_school.organization_id)
        session.add(identity)
        session.flush()
        student.learner_identity_id = identity.id
    case = LearnerTransferCase(
        reference=f"HT-{uuid.uuid4().hex[:12].upper()}",
        source_school_id=source_school.id,
        target_school_id=target_school.id,
        source_student_id=student.id,
        guardian_link_id=guardian.id,
        purpose=payload.purpose.strip(),
        consent_method=payload.consent_method,
        consent_reference=payload.consent_reference.strip(),
        consent_recorded_at=payload.consent_recorded_at,
        learner_first_name=student.person.first_name,
        learner_middle_name=student.person.middle_name,
        learner_last_name=student.person.last_name,
        learner_date_of_birth=student.person.date_of_birth,
        learner_gender=student.gender,
        learner_identification_number=student.learner_identification_number,
        learner_boarding_status=student.boarding_status,
        learner_nationality=student.nationality,
        guardian_first_name=guardian.person.first_name,
        guardian_last_name=guardian.person.last_name,
        guardian_relationship=guardian.relationship,
        guardian_phone=guardian.person.phone,
        guardian_email=guardian.person.email,
        created_by=context.actor,
    )
    session.add(case)
    session.flush()
    event_ids = []
    for school_id, action in ((source_school.id, "initiated"), (target_school.id, "received")):
        session.add(
            AuditEvent(
                school_id=school_id,
                entity_type="learner_transfer",
                entity_id=case.id,
                action=action,
                actor=context.actor,
                summary=f"{case.reference}: consented learner transfer {action}",
            )
        )
        event = enqueue_integration_event(
            session,
            school_id=school_id,
            event_type="learner.transfer.created",
            aggregate_type="learner_transfer",
            aggregate_id=case.id,
            payload={
                "transfer_id": case.id,
                "reference": case.reference,
                "source_unit_id": case.source_school_id,
                "target_unit_id": case.target_school_id,
                "status": case.status,
            },
            correlation_id=case.reference,
        )
        event_ids.append(event.id)
    session.commit()
    background_tasks.add_task(deliver_outbox_events, session.get_bind(), event_ids)
    return _case_payload(case, session, context.school_id)


@router.post("/learner-transfers/{case_id}/decision")
def decide_transfer(
    case_id: uuid.UUID,
    payload: LearnerTransferDecision,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
):
    case = session.scalar(
        select(LearnerTransferCase)
        .where(
            LearnerTransferCase.id == case_id,
            LearnerTransferCase.target_school_id == context.school_id,
        )
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Incoming transfer not found")
    if case.status == "accepted" and payload.action == "accept":
        return _case_payload(case, session, context.school_id)
    if case.status != "pending":
        raise HTTPException(status_code=409, detail="This transfer has already been decided")
    now = datetime.now(UTC)
    if payload.action == "reject":
        case.status = "rejected"
        case.decision_reason = payload.reason.strip() if payload.reason else None
        case.decided_by = context.actor
        case.decided_at = now
        event_ids = []
        for school_id in (case.source_school_id, case.target_school_id):
            session.add(
                AuditEvent(
                    school_id=school_id,
                    entity_type="learner_transfer",
                    entity_id=case.id,
                    action="rejected",
                    actor=context.actor,
                    summary=f"Rejected {case.reference}: {case.decision_reason}",
                )
            )
            event = enqueue_integration_event(
                session,
                school_id=school_id,
                event_type="learner.transfer.rejected",
                aggregate_type="learner_transfer",
                aggregate_id=case.id,
                payload={
                    "transfer_id": case.id,
                    "reference": case.reference,
                    "source_unit_id": case.source_school_id,
                    "target_unit_id": case.target_school_id,
                    "status": case.status,
                },
                correlation_id=case.reference,
            )
            event_ids.append(event.id)
        session.commit()
        background_tasks.add_task(deliver_outbox_events, session.get_bind(), event_ids)
        return _case_payload(case, session, context.school_id)
    academic_class = session.get(AcademicClass, payload.class_id)
    if academic_class is None or academic_class.school_id != context.school_id:
        raise HTTPException(status_code=422, detail="Class does not belong to the target section")
    stream = session.get(Stream, payload.stream_id) if payload.stream_id else None
    if stream is not None and stream.class_id != academic_class.id:
        raise HTTPException(status_code=422, detail="Stream does not belong to the selected class")
    period = resolve_period(
        session, school_id=context.school_id, period_id=payload.period_id, writable=True
    )
    source_student = session.get(Student, case.source_student_id)
    if source_student is None:
        raise HTTPException(status_code=409, detail="Source learner is no longer available")
    person = Person(
        first_name=case.learner_first_name,
        middle_name=case.learner_middle_name,
        last_name=case.learner_last_name,
        date_of_birth=case.learner_date_of_birth,
    )
    session.add(person)
    session.flush()
    student = Student(
        school_id=context.school_id,
        learner_identity_id=source_student.learner_identity_id,
        person_id=person.id,
        admission_no=payload.admission_no.strip(),
        learner_identification_number=case.learner_identification_number,
        gender=case.learner_gender,
        boarding_status=case.learner_boarding_status,
        nationality=case.learner_nationality,
    )
    session.add(student)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Admission number or learner identifier already exists in the target section",
        ) from error
    guardian_person = Person(
        first_name=case.guardian_first_name,
        last_name=case.guardian_last_name,
        phone=case.guardian_phone,
        email=case.guardian_email,
    )
    session.add(guardian_person)
    session.flush()
    session.add(
        GuardianLink(
            student_id=student.id,
            person_id=guardian_person.id,
            relationship=case.guardian_relationship,
            is_primary=True,
        )
    )
    session.add(
        Enrollment(
            student_id=student.id,
            class_id=academic_class.id,
            stream_id=payload.stream_id,
            period_id=period.id,
            academic_year=period.academic_year.year,
            term=period.sequence,
        )
    )
    fee_assignment = assign_published_general_fee(
        session,
        school_id=context.school_id,
        period_id=period.id,
        student_id=student.id,
        class_id=academic_class.id,
        actor=context.actor,
    )
    source_student.status = "transferred"
    case.status = "accepted"
    case.target_student_id = student.id
    case.decided_by = context.actor
    case.decided_at = now
    event_ids = []
    for school_id in (case.source_school_id, case.target_school_id):
        session.add(
            AuditEvent(
                school_id=school_id,
                entity_type="learner_transfer",
                entity_id=case.id,
                action="accepted",
                actor=context.actor,
                summary=f"Accepted {case.reference}; source financial history was preserved",
            )
        )
        event = enqueue_integration_event(
            session,
            school_id=school_id,
            event_type="learner.transfer.accepted",
            aggregate_type="learner_transfer",
            aggregate_id=case.id,
            payload={
                "transfer_id": case.id,
                "reference": case.reference,
                "stable_learner_id": source_student.learner_identity_id,
                "source_unit_id": case.source_school_id,
                "target_unit_id": case.target_school_id,
                "target_student_id": student.id,
                "status": case.status,
            },
            correlation_id=case.reference,
        )
        event_ids.append(event.id)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Admission number or learner identifier already exists in the target section",
        ) from error
    result = _case_payload(case, session, context.school_id)
    result["fee_assignment"] = fee_assignment
    background_tasks.add_task(deliver_outbox_events, session.get_bind(), event_ids)
    return result


@router.post("/learner-transfers/{case_id}/cancel")
def cancel_transfer(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
):
    case = session.scalar(
        select(LearnerTransferCase)
        .where(
            LearnerTransferCase.id == case_id,
            LearnerTransferCase.source_school_id == context.school_id,
        )
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Outgoing transfer not found")
    if case.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending transfer can be cancelled")
    case.status = "cancelled"
    case.decided_by = context.actor
    case.decided_at = datetime.now(UTC)
    event_ids = []
    for school_id in (case.source_school_id, case.target_school_id):
        session.add(
            AuditEvent(
                school_id=school_id,
                entity_type="learner_transfer",
                entity_id=case.id,
                action="cancelled",
                actor=context.actor,
                summary=f"Cancelled {case.reference}",
            )
        )
        event = enqueue_integration_event(
            session,
            school_id=school_id,
            event_type="learner.transfer.cancelled",
            aggregate_type="learner_transfer",
            aggregate_id=case.id,
            payload={
                "transfer_id": case.id,
                "reference": case.reference,
                "source_unit_id": case.source_school_id,
                "target_unit_id": case.target_school_id,
                "status": case.status,
            },
            correlation_id=case.reference,
        )
        event_ids.append(event.id)
    session.commit()
    background_tasks.add_task(deliver_outbox_events, session.get_bind(), event_ids)
    return _case_payload(case, session, context.school_id)
