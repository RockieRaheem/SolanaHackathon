from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.academic_structure import PROGRAMME_NAMES, template_classes
from harambeeone_api.auth import (
    ROLE_PERMISSIONS,
    AuthenticatedUser,
    SchoolContext,
    get_current_user,
    get_school_context,
)
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    AcademicClass,
    AuditEvent,
    School,
    SchoolMembership,
    SchoolOrganization,
    SchoolProgramme,
    Stream,
)
from harambeeone_api.schemas import SchoolAccessSummary, SchoolOnboardingCreate, SchoolSummary

router = APIRouter(prefix="/api/v1", tags=["institution onboarding"])


def _membership_school(user_id, session: Session) -> School | None:
    return session.scalars(
        select(School)
        .join(SchoolMembership)
        .where(SchoolMembership.auth_user_id == user_id)
        .order_by(SchoolMembership.created_at, SchoolMembership.id)
        .options(selectinload(School.programmes))
    ).first()


@router.get("/me/school", response_model=SchoolSummary)
def get_my_school(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SchoolSummary:
    school = _membership_school(user.id, session)
    if not school:
        raise HTTPException(status_code=404, detail="Institution setup is not complete")
    return SchoolSummary.model_validate(school, from_attributes=True)


@router.get("/me/context", response_model=SchoolAccessSummary)
def get_my_context(
    context: SchoolContext = Depends(get_school_context),
    session: Session = Depends(get_session),
) -> SchoolAccessSummary:
    school = session.scalar(
        select(School)
        .where(School.id == context.school_id)
        .options(selectinload(School.programmes))
    )
    if school is None:
        raise HTTPException(status_code=404, detail="Institution setup is not complete")
    summary = SchoolSummary.model_validate(school, from_attributes=True)
    return SchoolAccessSummary(
        **summary.model_dump(),
        role=context.role,
        permissions=sorted(ROLE_PERMISSIONS[context.role]),
    )


@router.post(
    "/onboarding/school",
    response_model=SchoolSummary,
    status_code=status.HTTP_201_CREATED,
)
def onboard_school(
    payload: SchoolOnboardingCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SchoolSummary:
    existing = _membership_school(user.id, session)
    if existing:
        return SchoolSummary.model_validate(existing, from_attributes=True)

    unit_type, unit_name = {
        frozenset({"day_care"}): ("day_care", "Day care section"),
        frozenset({"pre_primary"}): ("pre_primary", "Nursery section"),
        frozenset({"primary"}): ("primary", "Primary section"),
        frozenset({"lower_secondary"}): ("o_level", "O-Level section"),
        frozenset({"lower_secondary", "upper_secondary"}): (
            "secondary",
            "Secondary section",
        ),
    }[frozenset(payload.programme_codes)]
    organization = SchoolOrganization(
        name=payload.name, district=payload.district, emis_code=payload.emis_code
    )
    school = School(
        organization=organization,
        name=payload.name,
        unit_name=unit_name,
        unit_type=unit_type,
        district=payload.district,
        emis_code=payload.emis_code,
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
            streams=[Stream(name=stream_name) for stream_name in payload.default_streams],
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
        existing = _membership_school(user.id, session)
        if existing:
            return SchoolSummary.model_validate(existing, from_attributes=True)
        raise HTTPException(
            status_code=409,
            detail="This institution or user account is already registered",
        ) from error
    session.refresh(school, attribute_names=["programmes"])
    return SchoolSummary.model_validate(school, from_attributes=True)
