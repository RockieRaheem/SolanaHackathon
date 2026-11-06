import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.billing import assign_published_general_fee
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    AuditEvent,
    BalanceCarryForward,
    Enrollment,
    LearnerRollover,
    LearnerRolloverLine,
    PeriodClose,
    PeriodCloseLearner,
    Stream,
    Student,
)
from harambeeone_api.schemas import LearnerRolloverApply, LearnerRolloverDecision

router = APIRouter(prefix="/api/v1/learner-rollovers", tags=["learner rollover"])
ReadContext = Annotated[SchoolContext, Depends(require_permission("students:read"))]
WriteContext = Annotated[SchoolContext, Depends(require_permission("students:write"))]


def _next_period(session: Session, source: AcademicPeriod) -> AcademicPeriod | None:
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


def _load_rollover(
    session: Session,
    *,
    school_id: uuid.UUID,
    source_period_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> LearnerRollover | None:
    statement = (
        select(LearnerRollover)
        .where(LearnerRollover.school_id == school_id)
        .options(selectinload(LearnerRollover.lines))
    )
    if source_period_id is not None:
        statement = statement.where(LearnerRollover.source_period_id == source_period_id)
    if idempotency_key is not None:
        statement = statement.where(LearnerRollover.idempotency_key == idempotency_key)
    return session.scalar(statement)


def _periods_by_id(
    session: Session, source_id: uuid.UUID, destination_id: uuid.UUID
) -> dict[uuid.UUID, AcademicPeriod]:
    return {
        period.id: period
        for period in session.scalars(
            select(AcademicPeriod)
            .where(AcademicPeriod.id.in_((source_id, destination_id)))
            .options(joinedload(AcademicPeriod.academic_year))
        ).all()
    }


def _rollover_payload(session: Session, rollover: LearnerRollover) -> dict:
    periods = _periods_by_id(session, rollover.source_period_id, rollover.destination_period_id)
    source = periods[rollover.source_period_id]
    destination = periods[rollover.destination_period_id]
    return {
        "id": rollover.id,
        "source_period_id": rollover.source_period_id,
        "source_period_name": source.name,
        "source_academic_year_name": source.academic_year.name,
        "destination_period_id": rollover.destination_period_id,
        "destination_period_name": destination.name,
        "destination_academic_year_name": destination.academic_year.name,
        "source_snapshot_hash": rollover.source_snapshot_hash,
        "candidate_count": rollover.candidate_count,
        "placed_count": rollover.placed_count,
        "held_count": rollover.held_count,
        "completed_count": rollover.completed_count,
        "departed_count": rollover.departed_count,
        "applied_by": rollover.applied_by,
        "applied_at": rollover.applied_at,
        "lines": [
            {
                "student_id": line.student_id,
                "admission_no": line.admission_no,
                "learner_name": line.learner_name,
                "source_class_name": line.source_class_name,
                "source_stream_name": line.source_stream_name,
                "target_class_name": line.target_class_name,
                "target_stream_name": line.target_stream_name,
                "decision": line.decision,
                "reason": line.reason,
                "previous_status": line.previous_status,
                "new_status": line.new_status,
                "enrollment_id": line.enrollment_id,
            }
            for line in rollover.lines
        ],
    }


def _rollover_context(
    session: Session,
    *,
    school_id: uuid.UUID,
    source_period_id: uuid.UUID,
    destination_period_id: uuid.UUID,
) -> tuple[
    AcademicPeriod,
    AcademicPeriod,
    PeriodClose,
    list[PeriodCloseLearner],
    list[AcademicClass],
    dict[uuid.UUID, Student],
]:
    source = session.scalar(
        select(AcademicPeriod)
        .where(
            AcademicPeriod.id == source_period_id,
            AcademicPeriod.school_id == school_id,
        )
        .options(joinedload(AcademicPeriod.academic_year))
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source academic period not found")
    if source.status != "closed":
        raise HTTPException(status_code=409, detail="Close the source period before rollover")
    destination = session.scalar(
        select(AcademicPeriod)
        .where(
            AcademicPeriod.id == destination_period_id,
            AcademicPeriod.school_id == school_id,
        )
        .options(joinedload(AcademicPeriod.academic_year))
    )
    if destination is None:
        raise HTTPException(status_code=404, detail="Destination academic period not found")
    next_period = _next_period(session, source)
    if next_period is None:
        raise HTTPException(status_code=409, detail="Create the next period before rollover")
    if destination.id != next_period.id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Learners must roll into the next configured period: {next_period.name} · "
                f"{next_period.academic_year.name}"
            ),
        )
    if destination.status not in {"draft", "open"}:
        raise HTTPException(status_code=409, detail="The destination period must be draft or open")
    close = session.scalar(
        select(PeriodClose)
        .where(
            PeriodClose.school_id == school_id,
            PeriodClose.period_id == source.id,
        )
        .options(selectinload(PeriodClose.learners))
    )
    if close is None:
        raise HTTPException(status_code=409, detail="The source has no closing snapshot")
    if (
        session.scalar(
            select(BalanceCarryForward.id).where(
                BalanceCarryForward.school_id == school_id,
                BalanceCarryForward.source_period_id == source.id,
                BalanceCarryForward.destination_period_id == destination.id,
            )
        )
        is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Carry financial balances forward before rolling learners",
        )
    student_ids = [line.student_id for line in close.learners]
    students = (
        {
            student.id: student
            for student in session.scalars(
                select(Student).where(
                    Student.school_id == school_id,
                    Student.id.in_(student_ids),
                )
            ).all()
        }
        if student_ids
        else {}
    )
    candidates = [
        line
        for line in close.learners
        if line.student_id in students and students[line.student_id].status == "active"
    ]
    classes = list(
        session.scalars(
            select(AcademicClass)
            .where(AcademicClass.school_id == school_id)
            .options(selectinload(AcademicClass.streams))
            .order_by(AcademicClass.sort_order, AcademicClass.name)
        ).all()
    )
    return source, destination, close, candidates, classes, students


def _suggestions(
    source: AcademicPeriod,
    destination: AcademicPeriod,
    candidates: list[PeriodCloseLearner],
    classes: list[AcademicClass],
) -> list[dict]:
    class_by_id = {item.id: item for item in classes}
    later_class = {
        item.id: next(
            (candidate for candidate in classes if candidate.sort_order > item.sort_order),
            None,
        )
        for item in classes
    }
    stream_by_class_and_name = {
        (item.id, stream.name.casefold()): stream for item in classes for stream in item.streams
    }
    new_year = destination.academic_year.year > source.academic_year.year
    rows = []
    for candidate in candidates:
        source_class = class_by_id.get(candidate.class_id)
        target_class = (
            later_class.get(source_class.id) if new_year and source_class else source_class
        )
        if new_year and source_class and target_class is None:
            decision = "complete"
        elif new_year and source_class:
            decision = "promote"
        else:
            decision = "continue"
        target_stream = (
            stream_by_class_and_name.get((target_class.id, candidate.stream_name.casefold()))
            if target_class and candidate.stream_name
            else None
        )
        rows.append(
            {
                "student_id": candidate.student_id,
                "admission_no": candidate.admission_no,
                "learner_name": candidate.learner_name,
                "source_class_id": candidate.class_id,
                "source_class_name": candidate.class_name,
                "source_stream_id": candidate.stream_id,
                "source_stream_name": candidate.stream_name,
                "suggested_decision": decision,
                "suggested_target_class_id": target_class.id if target_class else None,
                "suggested_target_stream_id": target_stream.id if target_stream else None,
            }
        )
    return rows


@router.get("/preview")
def preview_rollover(
    source_period_id: uuid.UUID,
    destination_period_id: uuid.UUID,
    context: ReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    existing = _load_rollover(
        session, school_id=context.school_id, source_period_id=source_period_id
    )
    if existing is not None:
        if existing.destination_period_id != destination_period_id:
            raise HTTPException(status_code=409, detail="The source was rolled into another period")
        return {"already_applied": True, "rollover": _rollover_payload(session, existing)}
    source, destination, close, candidates, classes, students = _rollover_context(
        session,
        school_id=context.school_id,
        source_period_id=source_period_id,
        destination_period_id=destination_period_id,
    )
    return {
        "already_applied": False,
        "source_period": {
            "id": source.id,
            "name": source.name,
            "academic_year": source.academic_year.year,
            "academic_year_name": source.academic_year.name,
        },
        "destination_period": {
            "id": destination.id,
            "name": destination.name,
            "academic_year": destination.academic_year.year,
            "academic_year_name": destination.academic_year.name,
        },
        "source_snapshot_hash": close.snapshot_hash,
        "candidate_count": len(candidates),
        "excluded_inactive_count": len(close.learners) - len(candidates),
        "classes": [
            {
                "id": item.id,
                "name": item.name,
                "sort_order": item.sort_order,
                "streams": [{"id": stream.id, "name": stream.name} for stream in item.streams],
            }
            for item in classes
        ],
        "learners": _suggestions(source, destination, candidates, classes),
    }


@router.get("/{source_period_id}")
def get_rollover(
    source_period_id: uuid.UUID,
    context: ReadContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    rollover = _load_rollover(
        session, school_id=context.school_id, source_period_id=source_period_id
    )
    if rollover is None:
        raise HTTPException(status_code=404, detail="No learner rollover exists for this period")
    return _rollover_payload(session, rollover)


def _validate_decision(
    decision: LearnerRolloverDecision,
    source_line: PeriodCloseLearner,
    source: AcademicPeriod,
    destination: AcademicPeriod,
    classes: dict[uuid.UUID, AcademicClass],
    streams: dict[uuid.UUID, Stream],
) -> tuple[AcademicClass | None, Stream | None]:
    target_class = classes.get(decision.target_class_id) if decision.target_class_id else None
    target_stream = streams.get(decision.target_stream_id) if decision.target_stream_id else None
    if decision.target_class_id and target_class is None:
        raise HTTPException(status_code=422, detail="A target class is outside this school")
    if target_stream and (target_class is None or target_stream.class_id != target_class.id):
        raise HTTPException(status_code=422, detail="A target stream does not belong to its class")
    new_year = destination.academic_year.year > source.academic_year.year
    if decision.decision == "continue":
        if source_line.class_id is None:
            if target_class is not None:
                raise HTTPException(
                    status_code=422, detail="Class-free learners must remain ungraded"
                )
        elif not new_year and target_class and target_class.id != source_line.class_id:
            raise HTTPException(status_code=422, detail="Continuation must preserve the class")
        elif new_year:
            raise HTTPException(
                status_code=422, detail="Use repeat for a new-year same-class decision"
            )
        if source_line.class_id and target_class is None:
            raise HTTPException(status_code=422, detail="Continuation requires the source class")
    if decision.decision == "repeat":
        if not new_year or target_class is None or target_class.id != source_line.class_id:
            raise HTTPException(
                status_code=422, detail="Repetition must retain the class in a new year"
            )
    if decision.decision == "promote":
        source_class = classes.get(source_line.class_id)
        if not new_year or source_class is None or target_class is None:
            raise HTTPException(
                status_code=422, detail="Promotion requires a new year and target class"
            )
        if target_class.sort_order <= source_class.sort_order:
            raise HTTPException(status_code=422, detail="Promotion must move to a higher class")
    return target_class, target_stream


@router.post("/{source_period_id}", status_code=status.HTTP_201_CREATED)
def apply_rollover(
    source_period_id: uuid.UUID,
    payload: LearnerRolloverApply,
    response: Response,
    context: WriteContext,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    existing = _load_rollover(
        session, school_id=context.school_id, source_period_id=source_period_id
    )
    if existing is not None:
        if existing.destination_period_id != payload.destination_period_id:
            raise HTTPException(status_code=409, detail="The source was rolled into another period")
        response.status_code = status.HTTP_200_OK
        return {**_rollover_payload(session, existing), "idempotent_replay": True}
    source, destination, close, candidates, class_rows, students = _rollover_context(
        session,
        school_id=context.school_id,
        source_period_id=source_period_id,
        destination_period_id=payload.destination_period_id,
    )
    session.execute(
        select(AcademicPeriod)
        .where(AcademicPeriod.id.in_((source.id, destination.id)))
        .order_by(AcademicPeriod.id)
        .with_for_update()
    ).all()
    candidate_ids = {item.student_id for item in candidates}
    decision_by_student = {item.student_id: item for item in payload.decisions}
    if set(decision_by_student) != candidate_ids:
        missing = len(candidate_ids - set(decision_by_student))
        extra = len(set(decision_by_student) - candidate_ids)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Submit one decision for every active learner "
                f"({missing} missing, {extra} invalid)"
            ),
        )
    locked_students = {
        student.id: student
        for student in session.scalars(
            select(Student)
            .where(Student.id.in_(candidate_ids), Student.school_id == context.school_id)
            .order_by(Student.id)
            .with_for_update()
        ).all()
    }
    if len(locked_students) != len(candidate_ids) or any(
        item.status != "active" for item in locked_students.values()
    ):
        raise HTTPException(status_code=409, detail="A learner status changed; refresh the review")
    occupied = set(
        session.scalars(
            select(Enrollment.student_id).where(
                Enrollment.period_id == destination.id,
                Enrollment.student_id.in_(candidate_ids),
            )
        ).all()
    )
    if occupied:
        raise HTTPException(
            status_code=409,
            detail=f"{len(occupied)} learner(s) already have a destination placement",
        )
    classes = {item.id: item for item in class_rows}
    streams = {stream.id: stream for item in class_rows for stream in item.streams}
    placed = sum(
        decision.decision in {"continue", "promote", "repeat"} for decision in payload.decisions
    )
    held = sum(decision.decision == "hold" for decision in payload.decisions)
    completed = sum(decision.decision == "complete" for decision in payload.decisions)
    departed = sum(decision.decision == "depart" for decision in payload.decisions)
    rollover = LearnerRollover(
        school_id=context.school_id,
        source_close_id=close.id,
        source_period_id=source.id,
        destination_period_id=destination.id,
        idempotency_key=payload.idempotency_key,
        source_snapshot_hash=close.snapshot_hash,
        candidate_count=len(candidates),
        placed_count=placed,
        held_count=held,
        completed_count=completed,
        departed_count=departed,
        applied_by=context.actor,
        applied_at=datetime.now(UTC),
    )
    session.add(rollover)
    session.flush()
    for source_line in candidates:
        decision = decision_by_student[source_line.student_id]
        target_class, target_stream = _validate_decision(
            decision, source_line, source, destination, classes, streams
        )
        student = locked_students[source_line.student_id]
        enrollment = None
        if decision.decision in {"continue", "promote", "repeat"} and target_class:
            enrollment = Enrollment(
                student_id=student.id,
                class_id=target_class.id,
                stream_id=target_stream.id if target_stream else None,
                period_id=destination.id,
                academic_year=destination.academic_year.year,
                term=destination.sequence,
            )
            session.add(enrollment)
            session.flush()
            assign_published_general_fee(
                session,
                school_id=context.school_id,
                period_id=destination.id,
                student_id=student.id,
                class_id=target_class.id,
                actor=context.actor,
            )
        elif decision.decision in {"continue", "promote", "repeat", "hold"}:
            pass
        elif decision.decision == "complete":
            student.status = "completed"
        else:
            student.status = "withdrawn"
        session.flush()
        session.add(
            LearnerRolloverLine(
                rollover_id=rollover.id,
                school_id=context.school_id,
                source_close_learner_id=source_line.id,
                student_id=student.id,
                enrollment_id=enrollment.id if enrollment else None,
                source_class_id=source_line.class_id,
                source_stream_id=source_line.stream_id,
                target_class_id=target_class.id if target_class else None,
                target_stream_id=target_stream.id if target_stream else None,
                admission_no=source_line.admission_no,
                learner_name=source_line.learner_name,
                source_class_name=source_line.class_name,
                source_stream_name=source_line.stream_name,
                target_class_name=target_class.name if target_class else None,
                target_stream_name=target_stream.name if target_stream else None,
                decision=decision.decision,
                reason=decision.reason,
                previous_status="active",
                new_status=student.status,
            )
        )
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="student_rollover",
                entity_id=student.id,
                action=decision.decision,
                actor=context.actor,
                summary=(
                    f"{decision.decision.title()} {student.admission_no} into "
                    f"{destination.academic_year.name}, {destination.name}"
                ),
            )
        )
    session.flush()
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        replay = _load_rollover(
            session,
            school_id=context.school_id,
            source_period_id=source_period_id,
        ) or _load_rollover(
            session,
            school_id=context.school_id,
            idempotency_key=payload.idempotency_key,
        )
        if replay and replay.destination_period_id == payload.destination_period_id:
            response.status_code = status.HTTP_200_OK
            return {**_rollover_payload(session, replay), "idempotent_replay": True}
        raise HTTPException(
            status_code=409,
            detail="Rollover could not be applied because the destination changed",
        ) from error
    session.refresh(rollover)
    return {**_rollover_payload(session, rollover), "idempotent_replay": False}
