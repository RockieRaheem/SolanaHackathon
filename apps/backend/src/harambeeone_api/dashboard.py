import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.finance import record_payment
from harambeeone_api.financial_reporting import (
    aggregate_financial_totals,
    load_learner_financial_totals,
)
from harambeeone_api.models import (
    Enrollment,
    Payment,
    PaymentAllocation,
    Person,
    School,
    StatementTransaction,
    Student,
)
from harambeeone_api.onboarding import get_my_context
from harambeeone_api.periods import list_periods, resolve_period
from harambeeone_api.schemas import PaymentCreate

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class CashPayment(BaseModel):
    school_id: uuid.UUID = Field(alias="schoolId")
    learner_ref: str = Field(alias="learnerRef", min_length=3, max_length=50)
    payer_name: str = Field(alias="payerName", min_length=2, max_length=100)
    amount: int = Field(gt=0, le=100_000_000)
    note: str | None = Field(default=None, max_length=240)
    period_id: uuid.UUID | None = Field(default=None, alias="periodId")


@router.get("/bootstrap")
def dashboard_bootstrap(
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:read")),
) -> dict:
    """Load the shell context and dashboard through one authenticated request."""
    return {
        "school": get_my_context(context=context, session=session),
        "periods": list_periods(context=context, session=session),
        "overview": overview(
            school_id=context.school_id,
            period_id=period_id,
            session=session,
            context=context,
        ),
    }


@router.get("")
def overview(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("school:read")),
) -> dict:
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    summary = session.execute(
        select(
            School.id,
            School.name,
            select(func.count(StatementTransaction.id))
            .where(
                StatementTransaction.school_id == School.id,
                StatementTransaction.period_id == period.id,
                StatementTransaction.status != "reconciled",
            )
            .correlate(School)
            .scalar_subquery(),
            select(func.count(StatementTransaction.id))
            .where(
                StatementTransaction.school_id == School.id,
                StatementTransaction.period_id == period.id,
                StatementTransaction.status == "suggested",
            )
            .correlate(School)
            .scalar_subquery(),
        ).where(School.id == school_id)
    ).one_or_none()
    if summary is None:
        raise HTTPException(status_code=404, detail="No institution configured")
    school_id, school_name, unreconciled, suggested = summary
    active_student_ids = set(
        session.scalars(
            select(Student.id)
            .join(Enrollment, Enrollment.student_id == Student.id)
            .where(
                Student.school_id == school_id,
                Student.status == "active",
                Enrollment.period_id == period.id,
            )
        ).all()
    )
    learner_totals = load_learner_financial_totals(session, period=period)
    totals = aggregate_financial_totals(learner_totals.values())
    recent_payments = session.scalars(
        select(Payment)
        .where(Payment.school_id == school_id, Payment.period_id == period.id)
        .order_by(Payment.received_at.desc())
        .limit(8)
    ).all()
    learner_by_payment = {}
    if recent_payments:
        allocation_rows = session.execute(
            select(PaymentAllocation.payment_id, Student, Person)
            .join(Student, Student.id == PaymentAllocation.student_id)
            .join(Person, Person.id == Student.person_id)
            .where(PaymentAllocation.payment_id.in_([payment.id for payment in recent_payments]))
            .order_by(PaymentAllocation.payment_id, PaymentAllocation.id)
        ).all()
        for payment_id, student, person in allocation_rows:
            learner_by_payment.setdefault(payment_id, (student, person))
    activity = []
    for payment in recent_payments:
        learner = learner_by_payment.get(payment.id)
        if learner is None:
            continue
        student, person = learner
        activity.append(
            {
                "id": str(payment.id),
                "occurredAt": payment.received_at.isoformat(),
                "learner": f"{person.first_name} {person.last_name}",
                "learnerRef": student.admission_no,
                "description": (
                    f"{payment.transaction_type.replace('_', ' ').title()} · "
                    f"{payment.channel.replace('_', ' ').title()}"
                ),
                "amount": float(payment.amount),
                "currency": "UGX",
                "status": "RECONCILED",
            }
        )
    return {
        "mode": "LIVE",
        "school": {"id": str(school_id), "name": school_name},
        "period": {
            "id": str(period.id),
            "label": f"{period.name} · {period.academic_year.name}",
        },
        "generatedAt": datetime.now(UTC).isoformat(),
        "metrics": {
            "billed": float(totals.net_assessed),
            "collected": float(totals.net_collected),
            "outstanding": float(totals.outstanding),
            "activeLearners": len(active_student_ids),
            "accountsInArrears": sum(
                1
                for student_id in active_student_ids
                if learner_totals.get(student_id) and learner_totals[student_id].outstanding > 0
            ),
            "unreconciledCount": unreconciled,
            "suggestedMatches": suggested,
        },
        "weeklyCollections": [0, 0, 0, 0, 0, 0, float(totals.net_collected)],
        "activity": activity,
        "attention": [],
    }


@router.post("/cash-payments")
def cash_payment(
    payload: CashPayment,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
) -> dict:
    context.assert_school(payload.school_id)
    student = session.scalar(
        select(Student).where(
            Student.school_id == payload.school_id,
            Student.admission_no == payload.learner_ref.strip(),
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Learner reference not found")
    reference = f"CASH-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    result = record_payment(
        PaymentCreate(
            school_id=student.school_id,
            student_id=student.id,
            external_reference=reference,
            payer_name=payload.payer_name,
            note=payload.note,
            channel="cash",
            amount=payload.amount,
            period_id=payload.period_id,
        ),
        session,
        context,
    )
    return {"receiptNo": result.receipt_no, "paymentId": str(result.id)}
