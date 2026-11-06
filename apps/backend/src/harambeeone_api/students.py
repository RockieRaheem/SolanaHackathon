import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from harambeeone_api.academic_structure import GRADE_TEMPLATES, PROGRAMME_NAMES, template_classes
from harambeeone_api.auth import (
    AuthenticatedUser,
    SchoolContext,
    get_current_user,
    require_permission,
)
from harambeeone_api.billing import assign_published_general_fee
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AcademicClass,
    AuditEvent,
    Enrollment,
    FeeStructure,
    GuardianLink,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    Requirement,
    RequirementClass,
    School,
    SchoolMembership,
    SchoolOrganization,
    SchoolProgramme,
    Stream,
    Student,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import (
    BulkStudentImport,
    ClassSummary,
    ClassTemplateApply,
    ClassWrite,
    SchoolOnboardingCreate,
    SchoolSummary,
    StreamSummary,
    StudentCreate,
    StudentList,
    StudentProfileUpdate,
    StudentStatusUpdate,
    StudentSummary,
    StudentTransfer,
)

router = APIRouter(prefix="/api/v1", tags=["student registry"])


def _section_identity(programme_codes: list[str]) -> tuple[str, str]:
    return {
        frozenset({"day_care"}): ("day_care", "Day care section"),
        frozenset({"pre_primary"}): ("pre_primary", "Nursery section"),
        frozenset({"primary"}): ("primary", "Primary section"),
        frozenset({"lower_secondary"}): ("o_level", "O-Level section"),
        frozenset({"lower_secondary", "upper_secondary"}): (
            "secondary",
            "Secondary section",
        ),
    }[frozenset(programme_codes)]


@router.get("/schools", response_model=list[SchoolSummary])
def list_schools(
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:read")),
) -> list[SchoolSummary]:
    schools = session.scalars(
        select(School)
        .where(School.id == context.school_id)
        .order_by(School.name)
        .options(selectinload(School.programmes))
    ).all()
    return [SchoolSummary.model_validate(school, from_attributes=True) for school in schools]


@router.get("/academic-structure/templates")
def academic_structure_templates(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict]:
    return [
        {
            "code": code,
            "name": name,
            "classes": [
                {"canonical_code": grade_code, "name": grade_name}
                for grade_code, grade_name in GRADE_TEMPLATES.get(code, [])
            ],
        }
        for code, name in PROGRAMME_NAMES.items()
    ]


@router.post("/schools", response_model=SchoolSummary, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolOnboardingCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
) -> SchoolSummary:
    user = context.user
    if context.role != "owner":
        raise HTTPException(
            status_code=403, detail="Only an institution owner can add another school section"
        )
    existing_school = session.get(School, context.school_id)
    organization = existing_school.organization if existing_school else None
    if organization is None:
        organization = SchoolOrganization(
            name=existing_school.name if existing_school else payload.name,
            district=existing_school.district if existing_school else payload.district,
            emis_code=existing_school.emis_code if existing_school else payload.emis_code,
        )
        session.add(organization)
        session.flush()
    unit_type, unit_name = _section_identity(payload.programme_codes)
    duplicate_unit = session.scalar(
        select(School.id).where(
            School.organization_id == organization.id,
            School.unit_type == unit_type,
        )
    )
    if duplicate_unit is not None:
        raise HTTPException(status_code=409, detail=f"The {unit_name.lower()} already exists")
    school = School(
        organization=organization,
        name=organization.name,
        unit_name=unit_name,
        unit_type=unit_type,
        district=organization.district,
        emis_code=None,
    )
    school.programmes = [
        SchoolProgramme(
            programme_code=code,
            display_name=PROGRAMME_NAMES[code],
            sort_order=index,
        )
        for index, code in enumerate(payload.programme_codes, start=1)
    ]
    selected_codes = set(payload.canonical_codes)
    rows = template_classes(payload.programme_codes)
    if selected_codes:
        rows = [row for row in rows if row[0] in selected_codes]
    school.classes = [
        AcademicClass(
            name=name,
            level=programme_code,
            canonical_code=canonical_code,
            sort_order=index,
            streams=[Stream(name=stream) for stream in payload.default_streams],
        )
        for index, (canonical_code, name, programme_code) in enumerate(rows, start=1)
    ]
    school.memberships = [
        SchoolMembership(auth_user_id=user.id, member_email=user.email, role="owner")
    ]
    session.add(school)
    try:
        session.flush()
        session.add(
            AuditEvent(
                school_id=school.id,
                entity_type="school",
                entity_id=school.id,
                action="created",
                actor=user.email or str(user.id),
                summary=f"Created institution workspace for {school.name}",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This institution or school section is already registered"
        ) from error
    session.refresh(school, attribute_names=["programmes"])
    return SchoolSummary.model_validate(school, from_attributes=True)


@router.get("/schools/{school_id}/classes", response_model=list[ClassSummary])
def list_classes(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:read")),
) -> list[ClassSummary]:
    context.assert_school(school_id)
    rows = session.execute(
        select(
            AcademicClass,
            func.count(func.distinct(Enrollment.student_id)),
            func.count(func.distinct(FeeStructure.id)).filter(FeeStructure.status == "draft"),
            func.count(func.distinct(FeeStructure.id)).filter(
                FeeStructure.status == "published"
            ),
            func.count(func.distinct(RequirementClass.requirement_id)).filter(
                Requirement.status == "draft"
            ),
            func.count(func.distinct(RequirementClass.requirement_id)).filter(
                Requirement.status == "published"
            ),
        )
        .outerjoin(Enrollment, Enrollment.class_id == AcademicClass.id)
        .outerjoin(FeeStructure, FeeStructure.class_id == AcademicClass.id)
        .outerjoin(RequirementClass, RequirementClass.class_id == AcademicClass.id)
        .outerjoin(Requirement, Requirement.id == RequirementClass.requirement_id)
        .where(AcademicClass.school_id == school_id)
        .group_by(AcademicClass.id)
        .order_by(AcademicClass.sort_order)
        .options(selectinload(AcademicClass.streams))
    ).all()
    return [
        _class_summary(
            academic_class,
            student_count,
            draft_fee_count=draft_fee_count,
            published_fee_count=published_fee_count,
            draft_requirement_count=draft_requirement_count,
            published_requirement_count=published_requirement_count,
        )
        for (
            academic_class,
            student_count,
            draft_fee_count,
            published_fee_count,
            draft_requirement_count,
            published_requirement_count,
        ) in rows
    ]


@router.post(
    "/schools/{school_id}/classes",
    response_model=ClassSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_class(
    school_id: uuid.UUID,
    payload: ClassWrite,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
) -> ClassSummary:
    context.assert_school(school_id)
    if session.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="School not found")
    academic_class = AcademicClass(
        school_id=school_id,
        name=payload.name,
        level=payload.level,
        canonical_code=payload.canonical_code,
        sort_order=payload.sort_order,
    )
    academic_class.streams = [Stream(name=name) for name in payload.streams]
    session.add(academic_class)
    try:
        session.flush()
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="academic_class",
                entity_id=academic_class.id,
                action="created",
                actor=context.actor,
                summary=f"Created class {academic_class.name}",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A class with this name already exists"
        ) from error
    session.refresh(academic_class)
    return _class_summary(academic_class, 0)


@router.post(
    "/schools/{school_id}/classes/apply-template",
    response_model=list[ClassSummary],
    status_code=status.HTTP_201_CREATED,
)
def apply_class_template(
    school_id: uuid.UUID,
    payload: ClassTemplateApply,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
) -> list[ClassSummary]:
    context.assert_school(school_id)
    school = session.scalar(
        select(School)
        .where(School.id == school_id)
        .options(selectinload(School.programmes), selectinload(School.classes))
    )
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    existing_codes = {
        item.canonical_code for item in school.classes if item.canonical_code is not None
    }
    existing_names = {item.name.casefold() for item in school.classes}
    selected_codes = set(payload.canonical_codes)
    rows = template_classes(payload.programme_codes)
    if selected_codes:
        rows = [row for row in rows if row[0] in selected_codes]
    rows = [
        row
        for row in rows
        if row[0] not in existing_codes and row[1].casefold() not in existing_names
    ]
    next_order = max((item.sort_order for item in school.classes), default=0) + 1
    created = [
        AcademicClass(
            school_id=school.id,
            name=name,
            level=programme_code,
            canonical_code=canonical_code,
            sort_order=next_order + index,
            streams=[Stream(name=stream) for stream in payload.streams],
        )
        for index, (canonical_code, name, programme_code) in enumerate(rows)
    ]
    configured = {item.programme_code for item in school.programmes}
    for code in payload.programme_codes:
        if code not in configured:
            school.programmes.append(
                SchoolProgramme(
                    programme_code=code,
                    display_name=PROGRAMME_NAMES[code],
                    sort_order=len(school.programmes) + 1,
                )
            )
    session.add_all(created)
    try:
        session.flush()
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="academic_structure",
                entity_id=school.id,
                action="updated",
                actor=context.actor,
                summary=f"Added {len(created)} classes from standard templates",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="One or more classes already exist") from error
    for academic_class in created:
        session.refresh(academic_class, attribute_names=["streams"])
    return [_class_summary(academic_class, 0) for academic_class in created]


@router.put("/classes/{class_id}", response_model=ClassSummary)
def update_class(
    class_id: uuid.UUID,
    payload: ClassWrite,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
) -> ClassSummary:
    academic_class = session.scalar(
        select(AcademicClass)
        .where(AcademicClass.id == class_id, AcademicClass.school_id == context.school_id)
        .options(selectinload(AcademicClass.streams))
    )
    if academic_class is None:
        raise HTTPException(status_code=404, detail="Class not found")
    existing = {stream.name.casefold(): stream for stream in academic_class.streams}
    requested = {name.casefold(): name for name in payload.streams}
    removed = [stream for key, stream in existing.items() if key not in requested]
    for stream in removed:
        enrollment_count = session.scalar(
            select(func.count(Enrollment.id)).where(Enrollment.stream_id == stream.id)
        )
        if enrollment_count:
            raise HTTPException(
                status_code=409,
                detail=f"Stream {stream.name} still has enrolled learners and cannot be removed",
            )
    academic_class.name = payload.name
    academic_class.level = payload.level
    academic_class.canonical_code = payload.canonical_code
    academic_class.sort_order = payload.sort_order
    for stream in removed:
        session.delete(stream)
    for key, name in requested.items():
        if key in existing:
            existing[key].name = name
        else:
            academic_class.streams.append(Stream(name=name))
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="academic_class",
            entity_id=academic_class.id,
            action="updated",
            actor=context.actor,
            summary=f"Updated class {academic_class.name} and its streams",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Class or stream name already exists"
        ) from error
    session.refresh(academic_class, attribute_names=["streams"])
    count = session.scalar(
        select(func.count(func.distinct(Enrollment.student_id))).where(
            Enrollment.class_id == academic_class.id
        )
    )
    return _class_summary(academic_class, count or 0)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:manage")),
) -> Response:
    academic_class = session.scalar(
        select(AcademicClass).where(
            AcademicClass.id == class_id, AcademicClass.school_id == context.school_id
        )
    )
    if academic_class is None:
        raise HTTPException(status_code=404, detail="Class not found")
    enrollment_count = session.scalar(
        select(func.count(Enrollment.id)).where(Enrollment.class_id == class_id)
    )
    if enrollment_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This class has {enrollment_count} historical learner placement"
                f"{'s' if enrollment_count != 1 else ''}. Keep it for audit history or rename it."
            ),
        )
    fee_plans = session.scalars(
        select(FeeStructure)
        .where(FeeStructure.class_id == class_id)
        .options(
            selectinload(FeeStructure.items),
            selectinload(FeeStructure.installments),
            selectinload(FeeStructure.selected_learners),
        )
    ).all()
    if any(plan.status == "published" for plan in fee_plans):
        raise HTTPException(
            status_code=409,
            detail=(
                "This class has published financial history and cannot be deleted. "
                "Rename it if the section no longer uses it."
            ),
        )
    requirement_rows = session.execute(
        select(RequirementClass, Requirement)
        .join(Requirement, Requirement.id == RequirementClass.requirement_id)
        .where(RequirementClass.class_id == class_id)
        .options(selectinload(Requirement.classes), selectinload(Requirement.assignments))
    ).all()
    if any(
        requirement.status == "published" or requirement.assignments
        for _link, requirement in requirement_rows
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This class is part of published requirement history and cannot be deleted. "
                "Rename it if the section no longer uses it."
            ),
        )
    removed_drafts = len(fee_plans) + len(requirement_rows)
    for plan in fee_plans:
        session.delete(plan)
    for link, requirement in requirement_rows:
        if len(requirement.classes) == 1:
            session.delete(requirement)
        else:
            session.delete(link)
    programme = session.scalar(
        select(SchoolProgramme).where(
            SchoolProgramme.school_id == context.school_id,
            SchoolProgramme.programme_code == academic_class.level,
        )
    )
    other_class = session.scalar(
        select(AcademicClass.id).where(
            AcademicClass.school_id == context.school_id,
            AcademicClass.level == academic_class.level,
            AcademicClass.id != academic_class.id,
        )
    )
    if programme is not None and other_class is None:
        session.delete(programme)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="academic_class",
            entity_id=academic_class.id,
            action="deleted",
            actor=context.actor,
            summary=(
                f"Deleted unused class {academic_class.name} and {removed_drafts} "
                "unused draft configuration records"
            ),
        )
    )
    session.delete(academic_class)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _class_summary(
    academic_class: AcademicClass,
    student_count: int,
    *,
    draft_fee_count: int = 0,
    published_fee_count: int = 0,
    draft_requirement_count: int = 0,
    published_requirement_count: int = 0,
) -> ClassSummary:
    delete_blocker = None
    if student_count:
        delete_blocker = "Historical learner placements must be preserved"
    elif published_fee_count:
        delete_blocker = "Published financial history must be preserved"
    elif published_requirement_count:
        delete_blocker = "Published requirement history must be preserved"
    return ClassSummary(
        id=academic_class.id,
        name=academic_class.name,
        level=academic_class.level,
        canonical_code=academic_class.canonical_code,
        sort_order=academic_class.sort_order,
        student_count=student_count,
        draft_fee_count=draft_fee_count,
        published_fee_count=published_fee_count,
        draft_requirement_count=draft_requirement_count,
        published_requirement_count=published_requirement_count,
        requirement_count=draft_requirement_count + published_requirement_count,
        can_delete=delete_blocker is None,
        delete_blocker=delete_blocker,
        streams=[
            StreamSummary(id=stream.id, name=stream.name) for stream in academic_class.streams
        ],
    )


@router.get("/students", response_model=StudentList)
def list_students(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=100),
    class_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
) -> StudentList:
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    guardian_person = aliased(Person)
    statement = (
        select(Student, Person, Enrollment, AcademicClass, Stream, GuardianLink, guardian_person)
        .join(Person, Student.person_id == Person.id)
        .outerjoin(
            Enrollment,
            (Enrollment.student_id == Student.id) & (Enrollment.period_id == period.id),
        )
        .outerjoin(AcademicClass, AcademicClass.id == Enrollment.class_id)
        .outerjoin(Stream, Stream.id == Enrollment.stream_id)
        .join(
            GuardianLink,
            (GuardianLink.student_id == Student.id) & GuardianLink.is_primary.is_(True),
        )
        .join(guardian_person, guardian_person.id == GuardianLink.person_id)
        .where(Student.school_id == school_id, Student.status == "active")
    )
    if class_id:
        statement = statement.where(Enrollment.class_id == class_id)
    if search:
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Student.admission_no.ilike(term),
                Person.first_name.ilike(term),
                Person.last_name.ilike(term),
            )
        )
    rows = session.execute(statement.order_by(Person.last_name, Person.first_name)).all()
    items = [
        StudentSummary(
            id=student.id,
            admission_no=student.admission_no,
            full_name=" ".join(
                filter(None, [person.first_name, person.middle_name, person.last_name])
            ),
            gender=student.gender,
            status=student.status,
            class_name=academic_class.name if academic_class else "Day care / ungraded",
            stream_name=stream.name if stream else None,
            primary_guardian=f"{guardian.first_name} {guardian.last_name}",
            guardian_phone=guardian.phone or "",
        )
        for student, person, _enrollment, academic_class, stream, _link, guardian in rows
    ]
    return StudentList(items=items, total=len(items))


@router.get("/students/{student_id}")
def get_student_profile(
    student_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
) -> dict:
    student = session.scalar(
        select(Student)
        .where(Student.id == student_id, Student.school_id == context.school_id)
        .options(
            selectinload(Student.person),
            selectinload(Student.guardians).selectinload(GuardianLink.person),
            selectinload(Student.enrollments).selectinload(Enrollment.academic_class),
            selectinload(Student.enrollments).selectinload(Enrollment.stream),
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    enrollments = sorted(
        student.enrollments, key=lambda item: (item.academic_year, item.term), reverse=True
    )
    current = enrollments[0] if enrollments else None
    totals = dict(
        session.execute(
            select(LedgerEntry.entry_type, func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(LedgerEntry.student_id == student_id)
            .group_by(LedgerEntry.entry_type)
        ).all()
    )
    payments = session.scalars(
        select(Payment)
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .where(PaymentAllocation.student_id == student_id)
        .order_by(Payment.received_at.desc())
    ).all()
    charged = sum(
        (
            amount
            for entry_type, amount in totals.items()
            if amount > 0 and entry_type not in {"refund", "reversal"}
        ),
        Decimal("0"),
    )
    paid = -totals.get("payment", Decimal("0"))
    balance = sum(totals.values(), Decimal("0"))
    return {
        "id": student.id,
        "school_id": student.school_id,
        "admission_no": student.admission_no,
        "learner_identification_number": student.learner_identification_number,
        "first_name": student.person.first_name,
        "middle_name": student.person.middle_name,
        "last_name": student.person.last_name,
        "date_of_birth": student.person.date_of_birth,
        "gender": student.gender,
        "status": student.status,
        "boarding_status": student.boarding_status,
        "nationality": student.nationality,
        "previous_school": student.previous_school,
        "special_needs": student.special_needs,
        "placement": {
            "class_name": current.academic_class.name if current else None,
            "stream_name": current.stream.name if current and current.stream else None,
            "academic_year": current.academic_year if current else None,
            "term": current.term if current else None,
        },
        "guardians": [
            {
                "id": link.person.id,
                "first_name": link.person.first_name,
                "last_name": link.person.last_name,
                "name": f"{link.person.first_name} {link.person.last_name}",
                "relationship": link.relationship,
                "phone": link.person.phone,
                "email": link.person.email,
                "is_primary": link.is_primary,
            }
            for link in student.guardians
        ],
        "financials": {"billed": charged, "paid": paid, "balance": balance},
        "payments": [
            {
                "id": payment.id,
                "reference": payment.external_reference,
                "channel": payment.channel,
                "amount": payment.amount,
                "status": payment.status,
                "received_at": payment.received_at,
            }
            for payment in payments
        ],
    }


@router.patch("/students/{student_id}/status")
def update_student_status(
    student_id: uuid.UUID,
    payload: StudentStatusUpdate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
) -> dict:
    student = session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == context.school_id)
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    student.status = payload.status
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="student",
            entity_id=student.id,
            action="status_updated",
            actor=context.actor,
            summary=f"Changed learner {student.admission_no} status to {student.status}",
        )
    )
    session.commit()
    return {"id": student.id, "status": student.status}


@router.put("/students/{student_id}/profile")
def update_student_profile(
    student_id: uuid.UUID,
    payload: StudentProfileUpdate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
) -> dict:
    student = session.scalar(
        select(Student)
        .where(Student.id == student_id, Student.school_id == context.school_id)
        .options(selectinload(Student.person))
    )
    link = session.scalar(
        select(GuardianLink)
        .where(
            GuardianLink.student_id == student_id,
            GuardianLink.person_id == payload.guardian_id,
            GuardianLink.is_primary.is_(True),
        )
        .options(selectinload(GuardianLink.person))
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    if link is None:
        raise HTTPException(status_code=422, detail="Primary guardian does not belong to learner")
    student.person.first_name = payload.first_name.strip()
    student.person.middle_name = payload.middle_name.strip() if payload.middle_name else None
    student.person.last_name = payload.last_name.strip()
    student.person.date_of_birth = payload.date_of_birth
    student.gender = payload.gender
    student.learner_identification_number = payload.learner_identification_number or None
    student.boarding_status = payload.boarding_status
    student.nationality = payload.nationality.strip()
    student.previous_school = payload.previous_school or None
    student.special_needs = payload.special_needs or None
    link.person.first_name = payload.guardian_first_name.strip()
    link.person.last_name = payload.guardian_last_name.strip()
    link.person.phone = payload.guardian_phone.strip()
    link.person.email = str(payload.guardian_email) if payload.guardian_email else None
    link.relationship = payload.guardian_relationship
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="student",
            entity_id=student.id,
            action="updated",
            actor=context.actor,
            summary=f"Updated learner {student.admission_no} and primary guardian details",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Learner identification number already exists"
        ) from error
    return {"id": student.id, "updated": True}


@router.post("/students/{student_id}/transfer")
def transfer_student(
    student_id: uuid.UUID,
    payload: StudentTransfer,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
) -> dict:
    student = session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == context.school_id)
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id,
        academic_year=payload.academic_year,
        term=payload.term,
        writable=True,
    )
    academic_class = session.get(AcademicClass, payload.class_id)
    if academic_class is None or academic_class.school_id != student.school_id:
        raise HTTPException(status_code=422, detail="Class does not belong to the learner's school")
    stream = session.get(Stream, payload.stream_id) if payload.stream_id else None
    if stream is not None and stream.class_id != payload.class_id:
        raise HTTPException(status_code=422, detail="Stream does not belong to the selected class")
    enrollment = session.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.period_id == period.id,
        )
    )
    if enrollment is None:
        enrollment = Enrollment(
            student_id=student_id,
            period_id=period.id,
            academic_year=period.academic_year.year,
            term=period.sequence,
            class_id=payload.class_id,
            stream_id=payload.stream_id,
        )
        session.add(enrollment)
    else:
        enrollment.class_id = payload.class_id
        enrollment.stream_id = payload.stream_id
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="student_enrollment",
            entity_id=student.id,
            action="updated",
            actor=context.actor,
            summary=(
                f"Placed learner {student.admission_no} in {academic_class.name} "
                f"for {period.academic_year.name}, {period.name}"
            ),
        )
    )
    fee_assignment = assign_published_general_fee(
        session,
        school_id=context.school_id,
        period_id=period.id,
        student_id=student.id,
        class_id=payload.class_id,
        actor=context.actor,
    )
    session.commit()
    return {
        "student_id": student.id,
        "class_name": academic_class.name,
        "stream_name": stream.name if stream else None,
        "period_id": period.id,
        "academic_year": period.academic_year.year,
        "term": period.sequence,
        "fee_assignment": fee_assignment,
    }


def _register_student(payload: StudentCreate, session: Session) -> StudentSummary:
    period = resolve_period(
        session,
        school_id=payload.school_id,
        period_id=payload.period_id,
        academic_year=payload.academic_year,
        term=payload.term,
        writable=True,
    )
    academic_class = session.get(AcademicClass, payload.class_id) if payload.class_id else None
    if payload.class_id and (
        academic_class is None or academic_class.school_id != payload.school_id
    ):
        raise HTTPException(status_code=422, detail="Class does not belong to the selected school")
    if payload.class_id is None:
        day_care = session.scalar(
            select(SchoolProgramme.id).where(
                SchoolProgramme.school_id == payload.school_id,
                SchoolProgramme.programme_code == "day_care",
            )
        )
        if day_care is None:
            raise HTTPException(
                status_code=422,
                detail="Class-free registration is only available for a day-care programme",
            )
    stream = session.get(Stream, payload.stream_id) if payload.stream_id else None
    if stream is not None and stream.class_id != payload.class_id:
        raise HTTPException(status_code=422, detail="Stream does not belong to the selected class")
    if payload.fee_structure_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Fees are assigned through billing preview and publication, not registration",
        )

    person = Person(
        first_name=payload.first_name.strip(),
        middle_name=payload.middle_name,
        last_name=payload.last_name.strip(),
        date_of_birth=payload.date_of_birth,
    )
    session.add(person)
    session.flush()
    student_id = uuid.uuid4()
    student = Student(
        id=student_id,
        school_id=payload.school_id,
        person_id=person.id,
        admission_no=f"H1-{period.academic_year.year}-{str(student_id)[:8].upper()}",
        learner_identification_number=payload.learner_identification_number,
        gender=payload.gender,
        boarding_status=payload.boarding_status,
        nationality=payload.nationality,
        previous_school=payload.previous_school,
        special_needs=payload.special_needs,
    )
    session.add(student)
    if academic_class is not None:
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
    primary_guardian = None
    for guardian_payload in payload.guardians:
        guardian = Person(
            first_name=guardian_payload.first_name.strip(),
            last_name=guardian_payload.last_name.strip(),
            phone=guardian_payload.phone.strip(),
            email=str(guardian_payload.email) if guardian_payload.email else None,
        )
        session.add(guardian)
        session.flush()
        session.add(
            GuardianLink(
                student_id=student.id,
                person_id=guardian.id,
                relationship=guardian_payload.relationship,
                is_primary=guardian_payload.is_primary,
            )
        )
        if guardian_payload.is_primary:
            primary_guardian = guardian
    session.flush()
    assert primary_guardian is not None
    return StudentSummary(
        id=student.id,
        admission_no=student.admission_no,
        full_name=" ".join(filter(None, [person.first_name, person.middle_name, person.last_name])),
        gender=student.gender,
        status=student.status,
        class_name=academic_class.name if academic_class else "Day care / ungraded",
        stream_name=stream.name if stream else None,
        primary_guardian=f"{primary_guardian.first_name} {primary_guardian.last_name}",
        guardian_phone=primary_guardian.phone or "",
    )


@router.post("/students", response_model=StudentSummary, status_code=status.HTTP_201_CREATED)
def register_student(
    payload: StudentCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
) -> StudentSummary:
    context.assert_school(payload.school_id)
    result = _register_student(payload, session)
    fee_assignment = None
    if payload.class_id is not None:
        period = resolve_period(
            session,
            school_id=context.school_id,
            period_id=payload.period_id,
            academic_year=payload.academic_year,
            term=payload.term,
        )
        fee_assignment = assign_published_general_fee(
            session,
            school_id=context.school_id,
            period_id=period.id,
            student_id=result.id,
            class_id=payload.class_id,
            actor=context.actor,
        )
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="student",
            entity_id=result.id,
            action="created",
            actor=context.actor,
            summary=(
                f"Registered learner {result.admission_no}; general fee status "
                f"{fee_assignment['status'] if fee_assignment else 'not_applicable'}"
            ),
        )
    )
    session.commit()
    return result


@router.post("/student-imports")
def import_students(
    payload: BulkStudentImport,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:write")),
) -> dict:
    for student in payload.students:
        context.assert_school(student.school_id)
    imported: list[StudentSummary] = []
    try:
        for row_number, student in enumerate(payload.students, start=2):
            try:
                registered = _register_student(student, session)
                imported.append(registered)
                if student.class_id is not None:
                    period = resolve_period(
                        session,
                        school_id=context.school_id,
                        period_id=student.period_id,
                        academic_year=student.academic_year,
                        term=student.term,
                    )
                    assign_published_general_fee(
                        session,
                        school_id=context.school_id,
                        period_id=period.id,
                        student_id=registered.id,
                        class_id=student.class_id,
                        actor=context.actor,
                    )
            except HTTPException as error:
                raise HTTPException(
                    status_code=422, detail=f"Row {row_number}: {error.detail}"
                ) from error
            except IntegrityError as error:
                raise HTTPException(
                    status_code=409,
                    detail=f"Row {row_number}: learner identification already exists",
                ) from error
        if payload.validate_only:
            session.rollback()
        else:
            session.add(
                AuditEvent(
                    school_id=context.school_id,
                    entity_type="student_import",
                    entity_id=context.school_id,
                    action="created",
                    actor=context.actor,
                    summary=f"Imported {len(imported)} learners",
                )
            )
            session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        "valid": len(imported),
        "imported": 0 if payload.validate_only else len(imported),
        "validated_only": payload.validate_only,
    }
