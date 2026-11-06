import csv
import io
import uuid
from datetime import UTC, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.financial_reporting import (
    BALANCE_FORWARD_ENTRY_TYPES,
    load_student_financial_totals,
)
from harambeeone_api.models import (
    BillingAdjustment,
    Enrollment,
    FeeStructure,
    FeeStructureItem,
    GuardianLink,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Requirement,
    School,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)
from harambeeone_api.periods import resolve_period

router = APIRouter(prefix="/api/v1", tags=["learner accounts"])
PAYABLE_REQUIREMENT_TYPES = {"payment", "school_item"}
CREDIT_TYPES = {"discount", "sponsorship_credit", "waiver"}


def _money(value: Decimal | int) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def _display_name(student: Student) -> str:
    return " ".join(
        filter(
            None,
            [student.person.first_name, student.person.middle_name, student.person.last_name],
        )
    )


def _fee_sources(session: Session, assignment_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not assignment_ids:
        return {}
    assignments = session.scalars(
        select(StudentFeeAssignment)
        .where(StudentFeeAssignment.id.in_(assignment_ids))
        .options(
            selectinload(StudentFeeAssignment.fee_structure)
            .selectinload(FeeStructure.items)
            .selectinload(FeeStructureItem.category)
        )
    ).all()
    sources = {}
    for assignment in assignments:
        plan = assignment.fee_structure
        components = [
            {
                "name": item.category.name,
                "type": item.category.category_type,
                "amount": _money(item.amount),
            }
            for item in sorted(
                plan.items, key=lambda item: (item.category.priority, item.category.name)
            )
        ]
        types = {item["type"] for item in components}
        optional = any(item.category and not item.category.is_required for item in plan.items)
        if types == {"tuition"}:
            category = "tuition"
        elif optional or types.intersection({"uniform", "transport", "meals", "trip"}):
            category = "optional_purchase"
        else:
            category = "other_charge"
        sources[assignment.id] = {
            "description": plan.name,
            "category": category,
            "components": components,
        }
    return sources


def _statement_payload(
    session: Session,
    *,
    student_id: uuid.UUID,
    period_id: uuid.UUID,
    context: SchoolContext,
) -> dict:
    student = session.scalar(
        select(Student)
        .where(Student.id == student_id, Student.school_id == context.school_id)
        .options(
            selectinload(Student.person),
            selectinload(Student.guardians).selectinload(GuardianLink.person),
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    period = resolve_period(session, school_id=context.school_id, period_id=period_id)
    school = session.get(School, context.school_id)
    totals = load_student_financial_totals(session, period=period, student_id=student.id)
    opening_balance = totals.opening_balance

    ledger = session.scalars(
        select(LedgerEntry)
        .where(
            LedgerEntry.school_id == context.school_id,
            LedgerEntry.student_id == student.id,
            LedgerEntry.period_id == period.id,
        )
        .order_by(LedgerEntry.created_at, LedgerEntry.id)
    ).all()
    fee_sources = _fee_sources(
        session,
        {entry.fee_assignment_id for entry in ledger if entry.fee_assignment_id},
    )
    requirement_ids = {
        entry.requirement_assignment_id for entry in ledger if entry.requirement_assignment_id
    }
    requirement_sources = {}
    if requirement_ids:
        rows = session.execute(
            select(StudentRequirement, Requirement)
            .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
            .where(StudentRequirement.id.in_(requirement_ids))
        ).all()
        requirement_sources = {
            assignment.id: {
                "description": requirement.name,
                "category": (
                    "optional_purchase" if not requirement.is_mandatory else "requirement"
                ),
                "requirement_type": requirement.requirement_type,
                "unit": requirement.unit,
            }
            for assignment, requirement in rows
        }
    adjustment_ids = {
        entry.billing_adjustment_id for entry in ledger if entry.billing_adjustment_id
    }
    adjustments = (
        {
            item.id: item
            for item in session.scalars(
                select(BillingAdjustment).where(BillingAdjustment.id.in_(adjustment_ids))
            ).all()
        }
        if adjustment_ids
        else {}
    )
    payment_ids = {entry.payment_id for entry in ledger if entry.payment_id}
    payments = (
        {
            item.id: item
            for item in session.scalars(select(Payment).where(Payment.id.in_(payment_ids))).all()
        }
        if payment_ids
        else {}
    )
    allocations = (
        {
            item.payment_id: item
            for item in session.scalars(
                select(PaymentAllocation).where(
                    PaymentAllocation.payment_id.in_(payment_ids),
                    PaymentAllocation.student_id == student.id,
                )
            ).all()
        }
        if payment_ids
        else {}
    )

    enrollment = session.scalar(
        select(Enrollment)
        .where(Enrollment.student_id == student.id, Enrollment.period_id == period.id)
        .options(selectinload(Enrollment.academic_class), selectinload(Enrollment.stream))
    )
    events: list[dict] = []
    for entry in ledger:
        if entry.entry_type in BALANCE_FORWARD_ENTRY_TYPES:
            continue
        category = "other_charge"
        description = entry.description or entry.entry_type.replace("_", " ").title()
        detail = None
        components: list[dict] = []
        payer = None
        receipt_no = None
        if entry.fee_assignment_id and entry.fee_assignment_id in fee_sources:
            source = fee_sources[entry.fee_assignment_id]
            category = source["category"]
            description = source["description"]
            components = source["components"]
        elif (
            entry.requirement_assignment_id
            and entry.requirement_assignment_id in requirement_sources
        ):
            source = requirement_sources[entry.requirement_assignment_id]
            category = source["category"]
            description = source["description"]
            detail = "Requirement allocation"
        elif entry.billing_adjustment_id and entry.billing_adjustment_id in adjustments:
            adjustment = adjustments[entry.billing_adjustment_id]
            category = "credit" if adjustment.adjustment_type in CREDIT_TYPES else "other_charge"
            description = adjustment.description
            detail = adjustment.reason
        elif entry.payment_id and entry.payment_id in payments:
            payment = payments[entry.payment_id]
            allocation = allocations.get(payment.id)
            category = "payment"
            description = "Payment received"
            detail = (
                "Allocated to a requirement"
                if allocation and allocation.requirement_assignment_id
                else "Allocated to learner account"
            )
            payer = payment.payer_name
            receipt_no = payment.receipt_no
        elif entry.entry_type in CREDIT_TYPES:
            category = "credit"
        elif entry.entry_type == "payment":
            category = "payment"
        elif entry.entry_type in {"refund", "reversal"}:
            category = entry.entry_type
        elif entry.entry_type in {"opening_balance", "carried_balance"}:
            category = "balance_forward"
        events.append(
            {
                "id": str(entry.id),
                "occurred_at": entry.created_at,
                "entry_type": entry.entry_type,
                "category": category,
                "description": description,
                "detail": detail,
                "reference": entry.reference,
                "receipt_no": receipt_no,
                "payer_name": payer,
                "components": components,
                "quantity": None,
                "unit": None,
                "status": "posted",
                "amount": entry.amount,
                "is_financial": True,
                "sort_id": str(entry.id),
            }
        )

    physical_rows = session.execute(
        select(StudentRequirement, Requirement)
        .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
        .where(
            StudentRequirement.student_id == student.id,
            Requirement.school_id == context.school_id,
            Requirement.period_id == period.id,
            Requirement.requirement_type.not_in(PAYABLE_REQUIREMENT_TYPES),
        )
    ).all()
    for assignment, requirement in physical_rows:
        if assignment.is_waived:
            physical_status = "waived"
        elif assignment.fulfilled_quantity >= assignment.expected_quantity:
            physical_status = "received"
        elif assignment.fulfilled_quantity > 0:
            physical_status = "partially received"
        else:
            physical_status = "pending"
        events.append(
            {
                "id": f"requirement-{assignment.id}",
                "occurred_at": assignment.assigned_at,
                "entry_type": "physical_requirement",
                "category": "physical_requirement",
                "description": requirement.name,
                "detail": requirement.description,
                "reference": requirement.code,
                "receipt_no": None,
                "payer_name": None,
                "components": [],
                "quantity": assignment.expected_quantity,
                "unit": requirement.unit,
                "status": physical_status,
                "amount": Decimal("0"),
                "is_financial": False,
                "sort_id": str(assignment.id),
            }
        )
    events.sort(key=lambda item: (item["occurred_at"], item["sort_id"]))

    running_balance = opening_balance
    lines = [
        {
            "id": "opening-balance",
            "occurred_at": datetime.combine(period.opening_date, time.min, tzinfo=UTC),
            "entry_type": "opening_balance",
            "category": "balance_forward",
            "description": "Balance brought forward",
            "detail": "Closing balance from earlier academic periods",
            "reference": None,
            "receipt_no": None,
            "payer_name": None,
            "components": [],
            "quantity": None,
            "unit": None,
            "status": "derived",
            "amount": _money(opening_balance),
            "balance": _money(opening_balance),
            "is_financial": True,
        }
    ]
    for event in events:
        if event["is_financial"]:
            running_balance += event["amount"]
        lines.append(
            {
                key: (
                    _money(value) if key in {"amount", "quantity"} and value is not None else value
                )
                for key, value in event.items()
                if key != "sort_id"
            }
            | {"balance": _money(running_balance)}
        )

    primary = next(
        (link for link in student.guardians if link.is_primary and link.can_receive_statements),
        next((link for link in student.guardians if link.can_receive_statements), None),
    )
    return {
        "school": {"id": str(school.id), "name": school.name},
        "student": {
            "id": str(student.id),
            "admission_no": student.admission_no,
            "name": _display_name(student),
            "status": student.status,
        },
        "guardian": (
            {
                "name": f"{primary.person.first_name} {primary.person.last_name}",
                "relationship": primary.relationship,
                "phone": primary.person.phone,
                "email": primary.person.email,
            }
            if primary
            else None
        ),
        "period": {
            "id": str(period.id),
            "name": period.name,
            "academic_year": period.academic_year.year,
            "label": f"{period.academic_year.name} · {period.name}",
            "opening_date": period.opening_date,
            "closing_date": period.closing_date,
        },
        "placement": {
            "class_name": enrollment.academic_class.name if enrollment else None,
            "stream_name": enrollment.stream.name if enrollment and enrollment.stream else None,
        },
        "summary": {
            "opening_balance": _money(opening_balance),
            "charges": _money(totals.charges),
            "credits": _money(totals.credits),
            "payments": _money(totals.payments),
            "refunds": _money(totals.refunds),
            "reversals": _money(totals.reversals),
            "period_activity": _money(totals.period_activity),
            "closing_balance": _money(totals.closing_balance),
            "physical_requirements": len(physical_rows),
        },
        "lines": lines,
        "generated_at": datetime.now(UTC),
    }


@router.get("/students/{student_id}/statement")
def learner_statement(
    student_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
) -> dict:
    return _statement_payload(session, student_id=student_id, period_id=period_id, context=context)


@router.get("/students/{student_id}/statement.csv")
def learner_statement_csv(
    student_id: uuid.UUID,
    period_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("students:read")),
) -> Response:
    statement = _statement_payload(
        session, student_id=student_id, period_id=period_id, context=context
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([statement["school"]["name"], "Learner financial statement"])
    writer.writerow(["Learner", statement["student"]["name"]])
    writer.writerow(["Admission number", statement["student"]["admission_no"]])
    writer.writerow(["Period", statement["period"]["label"]])
    writer.writerow([])
    writer.writerow(
        ["Date", "Category", "Description", "Reference", "Payer", "Amount (UGX)", "Balance (UGX)"]
    )
    for line in statement["lines"]:
        writer.writerow(
            [
                line["occurred_at"].date().isoformat(),
                line["category"].replace("_", " ").title(),
                line["description"],
                line["reference"] or "",
                line["payer_name"] or "",
                line["amount"],
                line["balance"],
            ]
        )
    writer.writerow([])
    writer.writerow(["Closing balance", statement["summary"]["closing_balance"]])
    filename = (
        f"{statement['student']['admission_no']}-"
        f"{statement['period']['academic_year']}-{statement['period']['name']}.csv"
    )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
