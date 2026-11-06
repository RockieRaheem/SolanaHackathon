import hashlib
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.models import (
    FundingProgramme,
    Person,
    ProgrammeAllocation,
    School,
    Sponsor,
    Student,
)
from harambeeone_api.schemas import ProgrammeAllocationCreate, ProgrammeCreate

router = APIRouter(prefix="/api/v1/sponsor-programmes", tags=["sponsors"])


@router.get("")
def list_programmes(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("sponsors:read")),
):
    context.assert_school(school_id)
    rows = session.execute(
        select(FundingProgramme, Sponsor)
        .join(Sponsor, Sponsor.id == FundingProgramme.sponsor_id)
        .where(FundingProgramme.school_id == school_id)
        .order_by(FundingProgramme.created_at.desc())
    ).all()
    result = []
    for programme, sponsor in rows:
        allocated = session.scalar(
            select(func.coalesce(func.sum(ProgrammeAllocation.amount), 0)).where(
                ProgrammeAllocation.programme_id == programme.id
            )
        ) or Decimal("0")
        beneficiaries = (
            session.scalar(
                select(func.count(ProgrammeAllocation.id)).where(
                    ProgrammeAllocation.programme_id == programme.id
                )
            )
            or 0
        )
        result.append(
            {
                "id": programme.id,
                "name": programme.name,
                "description": programme.description,
                "sponsor_name": sponsor.name,
                "sponsor_type": sponsor.sponsor_type,
                "country": sponsor.country,
                "budget": programme.budget,
                "allocated": allocated,
                "available": programme.budget - allocated,
                "currency": programme.currency,
                "status": programme.status,
                "beneficiaries": beneficiaries,
            }
        )
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_programme(
    payload: ProgrammeCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("sponsors:write")),
):
    context.assert_school(payload.school_id)
    if session.get(School, payload.school_id) is None:
        raise HTTPException(status_code=404, detail="School not found")
    sponsor = Sponsor(
        name=payload.sponsor_name.strip(),
        sponsor_type=payload.sponsor_type,
        country=payload.country.strip(),
    )
    session.add(sponsor)
    session.flush()
    programme = FundingProgramme(
        sponsor_id=sponsor.id,
        school_id=payload.school_id,
        name=payload.name.strip(),
        description=payload.description,
        budget=payload.budget,
        currency=payload.currency,
    )
    session.add(programme)
    session.commit()
    return {"id": programme.id}


@router.get("/{programme_id}/allocations")
def list_allocations(
    programme_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("sponsors:read")),
):
    rows = session.execute(
        select(ProgrammeAllocation, Student, Person)
        .join(Student, Student.id == ProgrammeAllocation.student_id)
        .join(Person, Person.id == Student.person_id)
        .where(
            ProgrammeAllocation.programme_id == programme_id,
            ProgrammeAllocation.school_id == context.school_id,
        )
        .order_by(ProgrammeAllocation.created_at.desc())
    ).all()
    return [
        {
            "id": allocation.id,
            "student_id": student.id,
            "student_name": f"{person.first_name} {person.last_name}",
            "admission_no": student.admission_no,
            "beneficiary_ref": allocation.beneficiary_ref,
            "amount": allocation.amount,
            "currency": allocation.currency,
            "status": allocation.status,
            "created_at": allocation.created_at,
        }
        for allocation, student, person in rows
    ]


@router.post("/{programme_id}/allocations", status_code=status.HTTP_201_CREATED)
def allocate_beneficiary(
    programme_id: uuid.UUID,
    payload: ProgrammeAllocationCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("sponsors:write")),
):
    programme = session.scalar(
        select(FundingProgramme)
        .where(
            FundingProgramme.id == programme_id,
            FundingProgramme.school_id == context.school_id,
        )
        .with_for_update()
    )
    if programme is None:
        raise HTTPException(status_code=404, detail="Programme not found")
    student = session.get(Student, payload.student_id)
    if student is None or student.school_id != programme.school_id:
        raise HTTPException(
            status_code=422, detail="Learner does not belong to the programme school"
        )
    allocated = session.scalar(
        select(func.coalesce(func.sum(ProgrammeAllocation.amount), 0)).where(
            ProgrammeAllocation.programme_id == programme.id
        )
    ) or Decimal("0")
    if allocated + payload.amount > programme.budget:
        raise HTTPException(
            status_code=422, detail="Allocation exceeds the available programme budget"
        )
    reference = (
        "BEN-" + hashlib.sha256(f"{programme.id}:{student.id}".encode()).hexdigest()[:16].upper()
    )
    allocation = ProgrammeAllocation(
        programme_id=programme.id,
        school_id=programme.school_id,
        student_id=student.id,
        beneficiary_ref=reference,
        amount=payload.amount,
        currency=programme.currency,
    )
    session.add(allocation)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Learner is already allocated to this programme"
        ) from error
    return {"id": allocation.id, "beneficiary_ref": allocation.beneficiary_ref}
