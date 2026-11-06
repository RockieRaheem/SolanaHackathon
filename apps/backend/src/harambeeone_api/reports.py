import csv
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.finance import list_arrears
from harambeeone_api.financial_reporting import (
    FinancialTotals,
    aggregate_financial_totals,
    load_learner_financial_totals,
    load_school_financial_totals,
)
from harambeeone_api.models import (
    AcademicClass,
    BillingAdjustment,
    CashierCollectionBatch,
    Enrollment,
    FeeCategory,
    FeeStructure,
    FeeStructureItem,
    Payment,
    PaymentAllocation,
    Person,
    Requirement,
    StatementTransaction,
    Stream,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)
from harambeeone_api.periods import resolve_period

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

ZERO = Decimal("0")

REPORT_CATALOG = [
    ("collections_daily", "Daily collections", "Posted receipts grouped by business day."),
    ("collections_cashier", "Cashier collections", "Posted receipts grouped by cashier."),
    (
        "collections_channel",
        "Channel collections",
        "Posted receipts grouped by collection channel.",
    ),
    ("collections_class", "Class collections", "Posted receipts grouped by learner class."),
    ("collections_stream", "Stream collections", "Posted receipts grouped by class and stream."),
    ("learner_balances", "Learner balances", "Canonical opening, activity and closing balances."),
    (
        "arrears_aging",
        "Arrears aging",
        "Overdue balances in current, 1-30, 31-60, 61-90 and 90+ day bands.",
    ),
    (
        "fee_categories",
        "Fee categories",
        "Published fee assessment by category; payments remain general unless explicitly "
        "allocated.",
    ),
    (
        "requirements",
        "Requirements",
        "Assigned, paid, fulfilled and outstanding learner requirements.",
    ),
    ("adjustments", "Adjustments", "Discounts, sponsorships, waivers and additional charges."),
    (
        "corrections",
        "Reversals and refunds",
        "Evidence-preserving payment corrections and their original receipts.",
    ),
    (
        "unidentified",
        "Unidentified funds",
        "Imported funds awaiting a confirmed learner allocation.",
    ),
    (
        "reconciliation_variance",
        "Reconciliation control",
        "Provider totals and reconciliation status by channel.",
    ),
    ("cash_up", "Cash-up", "Expected cash, physical count and cashier variance."),
    ("deposits", "Deposits", "Cash-up deposit evidence and deposit differences."),
    (
        "billing_vs_collection",
        "Billing vs collection",
        "Canonical assessment and collection position by class and stream.",
    ),
]

REPORT_META = {key: (title, description) for key, title, description in REPORT_CATALOG}


def _date_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="End date must be on or after start date")
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC),
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC),
    )


def _validate_filters(
    session: Session,
    school_id: uuid.UUID,
    class_id: uuid.UUID | None,
    stream_id: uuid.UUID | None,
) -> None:
    if class_id and not session.scalar(
        select(AcademicClass.id).where(
            AcademicClass.id == class_id, AcademicClass.school_id == school_id
        )
    ):
        raise HTTPException(status_code=422, detail="The selected class is not part of this school")
    if stream_id and not session.scalar(
        select(Stream.id)
        .join(AcademicClass, AcademicClass.id == Stream.class_id)
        .where(Stream.id == stream_id, AcademicClass.school_id == school_id)
    ):
        raise HTTPException(
            status_code=422, detail="The selected stream is not part of this school"
        )


def _learner_context(
    session: Session,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    class_id: uuid.UUID | None,
    stream_id: uuid.UUID | None,
) -> dict[uuid.UUID, dict]:
    query = (
        select(Student, Person, AcademicClass, Stream)
        .join(Person, Person.id == Student.person_id)
        .outerjoin(
            Enrollment,
            (Enrollment.student_id == Student.id) & (Enrollment.period_id == period_id),
        )
        .outerjoin(AcademicClass, AcademicClass.id == Enrollment.class_id)
        .outerjoin(Stream, Stream.id == Enrollment.stream_id)
        .where(Student.school_id == school_id)
    )
    if class_id:
        query = query.where(Enrollment.class_id == class_id)
    if stream_id:
        query = query.where(Enrollment.stream_id == stream_id)
    return {
        student.id: {
            "student": student,
            "admission_no": student.admission_no,
            "learner": " ".join(
                part for part in (person.first_name, person.middle_name, person.last_name) if part
            ),
            "class": academic_class.name if academic_class else "Unplaced",
            "stream": stream.name if stream else "No stream",
        }
        for student, person, academic_class, stream in session.execute(query).all()
    }


def _report_payload(
    report_type: str,
    columns: list[dict],
    rows: list[dict],
    metrics: list[dict],
    start_date: date,
    end_date: date,
    note: str | None = None,
) -> dict:
    title, description = REPORT_META[report_type]
    return {
        "report_type": report_type,
        "title": title,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now(UTC),
        "columns": columns,
        "rows": rows,
        "metrics": metrics,
        "row_count": len(rows),
        "note": note,
    }


def _money_metric(label: str, value: Decimal, note: str = "") -> dict:
    return {"label": label, "value": value, "format": "money", "note": note}


def _number_metric(label: str, value: int, note: str = "") -> dict:
    return {"label": label, "value": value, "format": "number", "note": note}


def _collection_report(
    session: Session,
    report_type: str,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    start: datetime,
    end: datetime,
    learners: dict[uuid.UUID, dict],
    channel: str | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    payments = session.execute(
        select(Payment, PaymentAllocation)
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .where(
            Payment.school_id == school_id,
            Payment.period_id == period_id,
            Payment.received_at >= start,
            Payment.received_at < end,
            PaymentAllocation.student_id.in_(learners),
        )
        .order_by(Payment.received_at)
    ).all()
    if channel:
        payments = [row for row in payments if row[0].channel == channel]
    group_key = {
        "collections_daily": lambda payment, learner: payment.received_at.date().isoformat(),
        "collections_cashier": lambda payment, learner: payment.created_by or "System",
        "collections_channel": lambda payment, learner: payment.channel.replace("_", " ").title(),
        "collections_class": lambda payment, learner: learner["class"],
        "collections_stream": lambda payment, learner: f"{learner['class']} / {learner['stream']}",
    }[report_type]
    grouped: dict[str, dict] = {}
    receipts: set[uuid.UUID] = set()
    for payment, allocation in payments:
        learner = learners[allocation.student_id]
        label = group_key(payment, learner)
        item = grouped.setdefault(label, {"group": label, "receipts": set(), "amount": ZERO})
        item["receipts"].add(payment.id)
        item["amount"] += allocation.amount
        receipts.add(payment.id)
    rows = [
        {"group": item["group"], "receipts": len(item["receipts"]), "amount": item["amount"]}
        for item in grouped.values()
    ]
    rows.sort(key=lambda item: item["group"])
    total = sum((item["amount"] for item in rows), ZERO)
    return (
        [
            {"key": "group", "label": "Group", "format": "text"},
            {"key": "receipts", "label": "Receipts", "format": "number"},
            {"key": "amount", "label": "Net collected", "format": "money"},
        ],
        rows,
        [_money_metric("Net collected", total), _number_metric("Receipts", len(receipts))],
    )


def _centre_report(
    session: Session,
    report_type: str,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    start_date: date,
    end_date: date,
    class_id: uuid.UUID | None,
    stream_id: uuid.UUID | None,
    channel: str | None,
    context: SchoolContext,
) -> dict:
    if report_type not in REPORT_META:
        raise HTTPException(status_code=404, detail="Unknown report type")
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    start, end = _date_bounds(start_date, end_date)
    _validate_filters(session, school_id, class_id, stream_id)
    learners = _learner_context(session, school_id, period.id, class_id, stream_id)
    columns: list[dict]
    rows: list[dict]
    metrics: list[dict]
    note = None

    if report_type.startswith("collections_"):
        columns, rows, metrics = _collection_report(
            session, report_type, school_id, period.id, start, end, learners, channel
        )
    elif report_type in {"learner_balances", "billing_vs_collection"}:
        all_totals = load_learner_financial_totals(session, period=period)
        totals = {
            student_id: all_totals.get(student_id, FinancialTotals()) for student_id in learners
        }
        balance_rows = []
        for student_id, learner in learners.items():
            item = totals[student_id]
            balance_rows.append(
                {
                    "admission_no": learner["admission_no"],
                    "learner": learner["learner"],
                    "class": learner["class"],
                    "stream": learner["stream"],
                    "opening": item.opening_balance,
                    "assessed": item.net_assessed,
                    "collected": item.net_collected,
                    "activity": item.period_activity,
                    "closing": item.closing_balance,
                    "outstanding": item.outstanding,
                    "credit": item.credit_balance,
                }
            )
        if report_type == "billing_vs_collection":
            grouped: dict[tuple[str, str], dict] = {}
            for item in balance_rows:
                key = (item["class"], item["stream"])
                row = grouped.setdefault(
                    key,
                    {
                        "class": key[0],
                        "stream": key[1],
                        "learners": 0,
                        "assessed": ZERO,
                        "collected": ZERO,
                        "outstanding": ZERO,
                        "credit": ZERO,
                    },
                )
                row["learners"] += 1
                for field in ("assessed", "collected", "outstanding", "credit"):
                    row[field] += item[field]
            rows = sorted(grouped.values(), key=lambda item: (item["class"], item["stream"]))
            columns = [
                {"key": "class", "label": "Class", "format": "text"},
                {"key": "stream", "label": "Stream", "format": "text"},
                {"key": "learners", "label": "Learners", "format": "number"},
                {"key": "assessed", "label": "Net assessed", "format": "money"},
                {"key": "collected", "label": "Net collected", "format": "money"},
                {"key": "outstanding", "label": "Outstanding", "format": "money"},
                {"key": "credit", "label": "Credit", "format": "money"},
            ]
        else:
            rows = sorted(balance_rows, key=lambda item: (item["class"], item["learner"]))
            columns = [
                {"key": "admission_no", "label": "Admission", "format": "text"},
                {"key": "learner", "label": "Learner", "format": "text"},
                {"key": "class", "label": "Class", "format": "text"},
                {"key": "stream", "label": "Stream", "format": "text"},
                {"key": "opening", "label": "Opening", "format": "money"},
                {"key": "assessed", "label": "Net assessed", "format": "money"},
                {"key": "collected", "label": "Net collected", "format": "money"},
                {"key": "closing", "label": "Closing", "format": "money"},
            ]
        school_totals = aggregate_financial_totals(totals.values())
        metrics = [
            _money_metric("Opening balance", school_totals.opening_balance),
            _money_metric("Net assessed", school_totals.net_assessed),
            _money_metric("Net collected", school_totals.net_collected),
            _money_metric("Closing balance", school_totals.closing_balance),
        ]
    elif report_type == "arrears_aging":
        register = list_arrears(
            school_id=school_id,
            period_id=period.id,
            as_of=end_date,
            session=session,
            context=context,
            class_id=class_id,
            stream_id=stream_id,
        )
        rows = [
            {
                "admission_no": item.admission_no,
                "learner": item.student_name,
                "class": item.class_name,
                "stream": item.stream_name or "No stream",
                "current": item.aging["current"],
                "1_30": item.aging["1_30"],
                "31_60": item.aging["31_60"],
                "61_90": item.aging["61_90"],
                "90_plus": item.aging["90_plus"],
                "overdue": item.overdue_amount,
            }
            for item in register.items
        ]
        columns = [
            {"key": "admission_no", "label": "Admission", "format": "text"},
            {"key": "learner", "label": "Learner", "format": "text"},
            {"key": "class", "label": "Class", "format": "text"},
            {"key": "current", "label": "Current", "format": "money"},
            {"key": "1_30", "label": "1-30 days", "format": "money"},
            {"key": "31_60", "label": "31-60 days", "format": "money"},
            {"key": "61_90", "label": "61-90 days", "format": "money"},
            {"key": "90_plus", "label": "90+ days", "format": "money"},
            {"key": "overdue", "label": "Overdue", "format": "money"},
        ]
        metrics = [
            _money_metric("Total overdue", register.total_overdue),
            _number_metric("Accounts", register.total_accounts),
            _number_metric("High priority", register.critical_accounts),
        ]
    elif report_type == "requirements":
        result = session.execute(
            select(
                StudentRequirement,
                Requirement,
                func.coalesce(func.sum(PaymentAllocation.amount), 0),
            )
            .join(Requirement, Requirement.id == StudentRequirement.requirement_id)
            .outerjoin(
                PaymentAllocation,
                PaymentAllocation.requirement_assignment_id == StudentRequirement.id,
            )
            .where(
                Requirement.school_id == school_id,
                Requirement.period_id == period.id,
                StudentRequirement.student_id.in_(learners),
            )
            .group_by(StudentRequirement.id, Requirement.id)
        ).all()
        rows = []
        for assignment, requirement, paid in result:
            learner = learners[assignment.student_id]
            rows.append(
                {
                    "learner": learner["learner"],
                    "admission_no": learner["admission_no"],
                    "class": learner["class"],
                    "requirement": requirement.name,
                    "type": requirement.requirement_type.replace("_", " ").title(),
                    "expected": assignment.expected_amount,
                    "paid": paid,
                    "outstanding": max(assignment.expected_amount - paid, ZERO),
                    "quantity": assignment.expected_quantity,
                    "fulfilled": assignment.fulfilled_quantity,
                }
            )
        columns = [
            {"key": "admission_no", "label": "Admission", "format": "text"},
            {"key": "learner", "label": "Learner", "format": "text"},
            {"key": "class", "label": "Class", "format": "text"},
            {"key": "requirement", "label": "Requirement", "format": "text"},
            {"key": "expected", "label": "Expected", "format": "money"},
            {"key": "paid", "label": "Paid", "format": "money"},
            {"key": "outstanding", "label": "Outstanding", "format": "money"},
            {"key": "fulfilled", "label": "Qty fulfilled", "format": "number"},
        ]
        metrics = [
            _money_metric("Expected", sum((row["expected"] for row in rows), ZERO)),
            _money_metric("Paid", sum((row["paid"] for row in rows), ZERO)),
            _money_metric("Outstanding", sum((row["outstanding"] for row in rows), ZERO)),
            _number_metric("Assignments", len(rows)),
        ]
    elif report_type == "fee_categories":
        result = session.execute(
            select(
                FeeCategory.name,
                func.coalesce(
                    func.sum(
                        StudentFeeAssignment.amount
                        * FeeStructureItem.amount
                        / FeeStructure.total_amount
                    ),
                    0,
                ),
            )
            .join(FeeStructureItem, FeeStructureItem.category_id == FeeCategory.id)
            .join(FeeStructure, FeeStructure.id == FeeStructureItem.fee_structure_id)
            .join(StudentFeeAssignment, StudentFeeAssignment.fee_structure_id == FeeStructure.id)
            .where(
                FeeCategory.school_id == school_id,
                FeeStructure.period_id == period.id,
                FeeStructure.total_amount > 0,
                StudentFeeAssignment.student_id.in_(learners),
            )
            .group_by(FeeCategory.id, FeeCategory.name)
            .order_by(FeeCategory.name)
        ).all()
        rows = [{"category": name, "assessed": amount} for name, amount in result]
        columns = [
            {"key": "category", "label": "Fee category", "format": "text"},
            {"key": "assessed", "label": "Published assessment", "format": "money"},
        ]
        metrics = [
            _money_metric("Categorised assessment", sum((row["assessed"] for row in rows), ZERO)),
            _number_metric("Categories", len(rows)),
        ]
        note = (
            "Fee receipts are allocated to the learner's general fee balance, not to individual "
            "fee categories. This report therefore shows authoritative assessment by category "
            "without inventing a collection split."
        )
    elif report_type == "adjustments":
        result = session.execute(
            select(BillingAdjustment, Student, Person, FeeCategory)
            .join(Student, Student.id == BillingAdjustment.student_id)
            .join(Person, Person.id == Student.person_id)
            .outerjoin(FeeCategory, FeeCategory.id == BillingAdjustment.category_id)
            .where(
                BillingAdjustment.school_id == school_id,
                BillingAdjustment.period_id == period.id,
                BillingAdjustment.student_id.in_(learners),
                BillingAdjustment.created_at >= start,
                BillingAdjustment.created_at < end,
            )
            .order_by(BillingAdjustment.created_at.desc())
        ).all()
        rows = [
            {
                "date": adjustment.created_at.date(),
                "learner": learners[student.id]["learner"],
                "admission_no": student.admission_no,
                "class": learners[student.id]["class"],
                "type": adjustment.adjustment_type.replace("_", " ").title(),
                "category": category.name if category else "General",
                "status": adjustment.status.title(),
                "amount": adjustment.amount,
                "reason": adjustment.reason,
            }
            for adjustment, student, person, category in result
        ]
        columns = [
            {"key": "date", "label": "Date", "format": "date"},
            {"key": "admission_no", "label": "Admission", "format": "text"},
            {"key": "learner", "label": "Learner", "format": "text"},
            {"key": "class", "label": "Class", "format": "text"},
            {"key": "type", "label": "Adjustment", "format": "text"},
            {"key": "category", "label": "Category", "format": "text"},
            {"key": "status", "label": "Status", "format": "status"},
            {"key": "amount", "label": "Amount", "format": "money"},
            {"key": "reason", "label": "Reason", "format": "text"},
        ]
        metrics = [
            _money_metric("Adjustments", sum((row["amount"] for row in rows), ZERO)),
            _number_metric("Entries", len(rows)),
        ]
    elif report_type == "corrections":
        original = Payment.__table__.alias("original_payment")
        result = session.execute(
            select(Payment, original.c.receipt_no)
            .outerjoin(original, original.c.id == Payment.original_payment_id)
            .where(
                Payment.school_id == school_id,
                Payment.period_id == period.id,
                Payment.transaction_type.in_(("reversal", "refund")),
                Payment.received_at >= start,
                Payment.received_at < end,
            )
            .order_by(Payment.received_at.desc())
        ).all()
        rows = [
            {
                "date": payment.received_at.date(),
                "receipt": payment.receipt_no,
                "original_receipt": original_receipt,
                "type": payment.transaction_type.title(),
                "channel": payment.channel.replace("_", " ").title(),
                "amount": payment.amount,
                "actor": payment.created_by or "System",
                "reason": payment.correction_reason or "",
            }
            for payment, original_receipt in result
            if not channel or payment.channel == channel
        ]
        columns = [
            {"key": "date", "label": "Date", "format": "date"},
            {"key": "receipt", "label": "Correction receipt", "format": "text"},
            {"key": "original_receipt", "label": "Original receipt", "format": "text"},
            {"key": "type", "label": "Type", "format": "status"},
            {"key": "channel", "label": "Channel", "format": "text"},
            {"key": "amount", "label": "Amount", "format": "money"},
            {"key": "actor", "label": "Actor", "format": "text"},
            {"key": "reason", "label": "Reason", "format": "text"},
        ]
        metrics = [
            _money_metric("Net corrections", sum((row["amount"] for row in rows), ZERO)),
            _number_metric("Corrections", len(rows)),
        ]
    elif report_type in {"unidentified", "reconciliation_variance"}:
        statement_channel = "bank" if channel == "bank_transfer" else channel
        result = session.scalars(
            select(StatementTransaction)
            .where(
                StatementTransaction.school_id == school_id,
                StatementTransaction.period_id == period.id,
                StatementTransaction.transaction_date >= start_date,
                StatementTransaction.transaction_date <= end_date,
                *([StatementTransaction.channel == statement_channel] if statement_channel else []),
            )
            .order_by(StatementTransaction.transaction_date.desc())
        ).all()
        if report_type == "unidentified":
            result = [item for item in result if item.status == "unidentified"]
            rows = [
                {
                    "date": item.transaction_date,
                    "reference": item.source_reference,
                    "channel": item.channel.replace("_", " ").title(),
                    "description": item.description,
                    "amount": item.amount,
                    "reviewed_by": item.reviewed_by or "Not reviewed",
                }
                for item in result
            ]
            columns = [
                {"key": "date", "label": "Date", "format": "date"},
                {"key": "reference", "label": "Provider reference", "format": "text"},
                {"key": "channel", "label": "Channel", "format": "text"},
                {"key": "description", "label": "Description", "format": "text"},
                {"key": "amount", "label": "Amount", "format": "money"},
                {"key": "reviewed_by", "label": "Reviewed by", "format": "text"},
            ]
            metrics = [
                _money_metric("Unidentified funds", sum((row["amount"] for row in rows), ZERO)),
                _number_metric("Transactions", len(rows)),
            ]
        else:
            payment_ids = {item.payment_id for item in result if item.payment_id}
            posted = (
                {
                    payment.id: payment.amount
                    for payment in session.scalars(
                        select(Payment).where(Payment.id.in_(payment_ids))
                    ).all()
                }
                if payment_ids
                else {}
            )
            grouped: dict[str, dict] = {}
            for item in result:
                row = grouped.setdefault(
                    item.channel,
                    {
                        "channel": item.channel.replace("_", " ").title(),
                        "transactions": 0,
                        "provider_amount": ZERO,
                        "reconciled_amount": ZERO,
                        "unresolved_amount": ZERO,
                        "posted_amount": ZERO,
                        "variance": ZERO,
                    },
                )
                row["transactions"] += 1
                row["provider_amount"] += item.amount
                if item.status == "reconciled":
                    row["reconciled_amount"] += item.amount
                    row["posted_amount"] += posted.get(item.payment_id, ZERO)
                else:
                    row["unresolved_amount"] += item.amount
            for row in grouped.values():
                row["variance"] = row["reconciled_amount"] - row["posted_amount"]
            rows = sorted(grouped.values(), key=lambda item: item["channel"])
            columns = [
                {"key": "channel", "label": "Channel", "format": "text"},
                {"key": "transactions", "label": "Transactions", "format": "number"},
                {"key": "provider_amount", "label": "Provider total", "format": "money"},
                {"key": "reconciled_amount", "label": "Reconciled", "format": "money"},
                {"key": "posted_amount", "label": "Posted receipts", "format": "money"},
                {"key": "unresolved_amount", "label": "Unresolved", "format": "money"},
                {"key": "variance", "label": "Reconciled variance", "format": "money"},
            ]
            unresolved = sum((item.amount for item in result if item.status != "reconciled"), ZERO)
            variance = sum((row["variance"] for row in rows), ZERO)
            metrics = [
                _money_metric("Provider total", sum((item.amount for item in result), ZERO)),
                _money_metric("Unresolved", unresolved),
                _money_metric("Reconciled variance", variance),
                _number_metric("Transactions", len(result)),
            ]
    elif report_type in {"cash_up", "deposits"}:
        batches = session.scalars(
            select(CashierCollectionBatch)
            .where(
                CashierCollectionBatch.school_id == school_id,
                CashierCollectionBatch.period_id == period.id,
                CashierCollectionBatch.business_date >= start_date,
                CashierCollectionBatch.business_date <= end_date,
            )
            .order_by(
                CashierCollectionBatch.business_date.desc(), CashierCollectionBatch.cashier_actor
            )
        ).all()
        if report_type == "cash_up":
            rows = [
                {
                    "date": item.business_date,
                    "cashier": item.cashier_actor,
                    "status": item.status.replace("_", " ").title(),
                    "expected": item.expected_cash,
                    "counted": item.counted_cash,
                    "variance": item.variance,
                    "deposit": item.deposit_amount,
                }
                for item in batches
            ]
            columns = [
                {"key": "date", "label": "Business date", "format": "date"},
                {"key": "cashier", "label": "Cashier", "format": "text"},
                {"key": "status", "label": "Status", "format": "status"},
                {"key": "expected", "label": "Expected cash", "format": "money"},
                {"key": "counted", "label": "Counted cash", "format": "money"},
                {"key": "variance", "label": "Variance", "format": "money"},
                {"key": "deposit", "label": "Deposit", "format": "money"},
            ]
            metrics = [
                _money_metric("Expected cash", sum((item.expected_cash for item in batches), ZERO)),
                _money_metric("Counted cash", sum((item.counted_cash for item in batches), ZERO)),
                _money_metric("Net variance", sum((item.variance for item in batches), ZERO)),
                _number_metric("Batches", len(batches)),
            ]
        else:
            rows = [
                {
                    "date": item.business_date,
                    "cashier": item.cashier_actor,
                    "status": item.status.replace("_", " ").title(),
                    "reference": item.deposit_reference or "Not recorded",
                    "counted": item.counted_cash,
                    "deposit": item.deposit_amount,
                    "difference": item.deposit_amount - item.counted_cash,
                }
                for item in batches
            ]
            columns = [
                {"key": "date", "label": "Business date", "format": "date"},
                {"key": "cashier", "label": "Cashier", "format": "text"},
                {"key": "status", "label": "Status", "format": "status"},
                {"key": "reference", "label": "Deposit reference", "format": "text"},
                {"key": "counted", "label": "Counted cash", "format": "money"},
                {"key": "deposit", "label": "Deposited", "format": "money"},
                {"key": "difference", "label": "Difference", "format": "money"},
            ]
            metrics = [
                _money_metric("Counted cash", sum((item.counted_cash for item in batches), ZERO)),
                _money_metric("Deposited", sum((item.deposit_amount for item in batches), ZERO)),
                _money_metric(
                    "Deposit difference",
                    sum((item.deposit_amount - item.counted_cash for item in batches), ZERO),
                ),
                _number_metric("Batches", len(batches)),
            ]
    else:
        raise HTTPException(status_code=404, detail="Unknown report type")
    return _report_payload(report_type, columns, rows, metrics, start_date, end_date, note)


@router.get("/centre")
def report_catalog(
    school_id: uuid.UUID,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reports:read")),
):
    context.assert_school(school_id)
    classes = session.scalars(
        select(AcademicClass)
        .where(AcademicClass.school_id == school_id)
        .order_by(AcademicClass.sort_order)
        .options(selectinload(AcademicClass.streams))
    ).all()
    return {
        "reports": [
            {"key": key, "title": title, "description": description}
            for key, title, description in REPORT_CATALOG
        ],
        "classes": [
            {
                "id": item.id,
                "name": item.name,
                "streams": [{"id": stream.id, "name": stream.name} for stream in item.streams],
            }
            for item in classes
        ],
    }


@router.get("/centre/{report_type}")
def report_centre(
    report_type: str,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    start_date: date,
    end_date: date,
    class_id: uuid.UUID | None = None,
    stream_id: uuid.UUID | None = None,
    channel: str | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reports:read")),
):
    return _centre_report(
        session,
        report_type,
        school_id,
        period_id,
        start_date,
        end_date,
        class_id,
        stream_id,
        channel,
        context,
    )


@router.get("/centre/{report_type}/export.csv")
def export_report_centre(
    report_type: str,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    start_date: date,
    end_date: date,
    class_id: uuid.UUID | None = None,
    stream_id: uuid.UUID | None = None,
    channel: str | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reports:read")),
):
    report = _centre_report(
        session,
        report_type,
        school_id,
        period_id,
        start_date,
        end_date,
        class_id,
        stream_id,
        channel,
        context,
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([column["label"] for column in report["columns"]])
    for row in report["rows"]:
        writer.writerow([row.get(column["key"], "") for column in report["columns"]])
    filename = f"harambeeone-{report_type}-{start_date}-{end_date}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/collections")
def collections_report(
    school_id: uuid.UUID,
    start_date: date,
    end_date: date,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reports:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="End date must be on or after start date")
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    latest_class_id = (
        select(Enrollment.class_id)
        .where(Enrollment.student_id == Student.id, Enrollment.period_id == period.id)
        .order_by(Enrollment.academic_year.desc(), Enrollment.term.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Payment, PaymentAllocation, Student, Person, AcademicClass)
        .select_from(Payment)
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .join(Student, Student.id == PaymentAllocation.student_id)
        .join(Person, Person.id == Student.person_id)
        .outerjoin(AcademicClass, AcademicClass.id == latest_class_id)
        .where(
            Payment.school_id == school_id,
            Payment.period_id == period.id,
            Payment.received_at >= start,
            Payment.received_at < end,
        )
        .order_by(Payment.received_at.desc())
        .limit(5000)
    ).all()
    totals = load_school_financial_totals(session, period=period)
    channels: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    classes: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    transactions_by_payment = {}
    for payment, allocation, student, person, academic_class in rows:
        channels[payment.channel] += allocation.amount
        classes[academic_class.name if academic_class else "Unplaced"] += allocation.amount
        transaction = transactions_by_payment.setdefault(
            payment.id,
            {
                "id": payment.id,
                "receipt_no": payment.receipt_no,
                "received_at": payment.received_at,
                "student_name": f"{person.first_name} {person.last_name}",
                "admission_no": student.admission_no,
                "class_name": academic_class.name if academic_class else "Unplaced",
                "channel": payment.channel,
                "reference": payment.external_reference,
                "amount": Decimal("0"),
            },
        )
        transaction["amount"] += allocation.amount
    transactions = list(transactions_by_payment.values())
    collected = sum((row["amount"] for row in transactions), Decimal("0"))
    return {
        "start_date": start_date,
        "end_date": end_date,
        "billed": totals.net_assessed,
        "collected": collected,
        "outstanding": totals.outstanding,
        "credit_balance": totals.credit_balance,
        "opening_balance": totals.opening_balance,
        "period_activity": totals.period_activity,
        "closing_balance": totals.closing_balance,
        "collection_rate": (
            float(collected / totals.net_assessed * 100) if totals.net_assessed else 0
        ),
        "transaction_count": len(transactions),
        "average_payment": collected / len(transactions) if transactions else 0,
        "by_channel": [
            {"label": key.replace("_", " ").title(), "amount": amount}
            for key, amount in sorted(channels.items())
        ],
        "by_class": [{"label": key, "amount": amount} for key, amount in sorted(classes.items())],
        "transactions": transactions,
    }
