import csv
import hashlib
import io
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from harambeeone_api.auth import SchoolContext, require_permission
from harambeeone_api.database import get_session
from harambeeone_api.finance import _next_payment_receipt, _resolved_allocations
from harambeeone_api.models import (
    AuditEvent,
    CashierBatchPayment,
    CashierCollectionBatch,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Person,
    StatementImport,
    StatementTransaction,
    StellarAnchor,
    Student,
)
from harambeeone_api.periods import resolve_period
from harambeeone_api.schemas import (
    CashBatchDecision,
    CashBatchOpen,
    CashBatchSubmit,
    PaymentCreate,
    ReconciliationConfirm,
    ReconciliationDecision,
    ReconciliationUndo,
    StatementFileImportCreate,
    StatementImportCreate,
)

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])
KAMPALA = ZoneInfo("Africa/Kampala")
HEADER_ALIASES = {
    "bank": {
        "date": {"date", "transactiondate", "valuedate"},
        "reference": {"reference", "transactionreference", "transactionid", "ref"},
        "amount": {"amount", "credit", "creditamount"},
        "description": {"description", "narration", "details"},
    },
    "mobile_money": {
        "date": {"date", "transactiondate", "completiontime", "timestamp"},
        "reference": {"reference", "transactionid", "financialtransactionid", "id"},
        "amount": {"amount", "receivedamount", "credit", "transactionamount"},
        "description": {"description", "payer", "customername", "narrative"},
    },
    "schoolpay": {
        "date": {"date", "paymentdate", "transactiondate"},
        "reference": {"reference", "paymentreference", "transactionid", "receiptno"},
        "amount": {"amount", "paidamount", "paymentamount"},
        "description": {"description", "studentcode", "studentname", "payer"},
    },
}


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold().lstrip("\ufeff"))


def _parse_date(value: str, row_number: int) -> date:
    cleaned = value.strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail=f"Row {row_number}: invalid transaction date")


def _parse_amount(value: str, row_number: int) -> Decimal:
    cleaned = re.sub(r"[^0-9.()-]", "", value).replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail=f"Row {row_number}: invalid amount") from error
    if amount <= 0:
        raise HTTPException(status_code=422, detail=f"Row {row_number}: amount must be positive")
    return amount


def _parse_file(source_type: str, content: str) -> list[dict]:
    try:
        rows = list(csv.reader(io.StringIO(content)))
    except csv.Error as error:
        raise HTTPException(status_code=422, detail="The CSV file is malformed") from error
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="The CSV needs a header and at least one row")
    normalized = [_header(value) for value in rows[0]]
    aliases = HEADER_ALIASES[source_type]
    indexes: dict[str, list[int]] = {}
    for field, choices in aliases.items():
        matches = [index for index, value in enumerate(normalized) if value in choices]
        if field != "description" and not matches:
            raise HTTPException(
                status_code=422,
                detail=f"{source_type.replace('_', ' ').title()} CSV is missing a {field} column",
            )
        indexes[field] = matches
    parsed = []
    seen = set()
    for row_number, row in enumerate(rows[1:], 2):

        def get(index: int) -> str:
            return row[index].strip() if index < len(row) else ""

        reference = get(indexes["reference"][0]).upper()
        if not reference:
            raise HTTPException(status_code=422, detail=f"Row {row_number}: reference is required")
        if reference in seen:
            raise HTTPException(
                status_code=422, detail=f"Row {row_number}: duplicate reference {reference}"
            )
        seen.add(reference)
        descriptions = [get(index) for index in indexes["description"]]
        parsed.append(
            {
                "transaction_date": _parse_date(get(indexes["date"][0]), row_number),
                "source_reference": reference,
                "description": " · ".join(value for value in descriptions if value)[:240],
                "amount": _parse_amount(get(indexes["amount"][0]), row_number),
            }
        )
    if len(parsed) > 500:
        raise HTTPException(status_code=422, detail="Import at most 500 transactions at a time")
    return parsed


def _suggestions(session: Session, school_id: uuid.UUID) -> list[tuple[Student, Person]]:
    return session.execute(
        select(Student, Person)
        .join(Person, Person.id == Student.person_id)
        .where(Student.school_id == school_id, Student.status == "active")
    ).all()


def _suggest_learner(
    learners: list[tuple[Student, Person]], reference: str, description: str
) -> tuple[uuid.UUID | None, Decimal | None, str | None]:
    haystack = f" {reference} {description} ".casefold()
    exact = [
        student
        for student, _ in learners
        if re.search(
            rf"(?<![a-z0-9]){re.escape(student.admission_no.casefold())}(?![a-z0-9])",
            haystack,
        )
    ]
    if len(exact) == 1:
        return exact[0].id, Decimal("1.0000"), "Exact admission number in source record"
    named = []
    for student, person in learners:
        full_name = f"{person.first_name} {person.last_name}".strip().casefold()
        if len(full_name) >= 5 and full_name in haystack:
            named.append(student)
    if len(named) == 1:
        return named[0].id, Decimal("0.8500"), "Unique learner name in source record"
    return None, None, None


def _refresh_import_status(session: Session, import_id: uuid.UUID) -> None:
    open_count = session.scalar(
        select(func.count(StatementTransaction.id)).where(
            StatementTransaction.import_id == import_id,
            StatementTransaction.status.in_(("suggested", "unmatched")),
        )
    )
    batch = session.get(StatementImport, import_id)
    if batch:
        batch.status = "review" if open_count else "complete"


def _import_rows(
    session: Session,
    *,
    school_id: uuid.UUID,
    period_id: uuid.UUID,
    file_name: str,
    source_type: str,
    content_hash: str,
    idempotency_key: str,
    rows: list[dict],
    context: SchoolContext,
) -> StatementImport:
    prior_key = session.scalar(
        select(StatementImport).where(
            StatementImport.school_id == school_id,
            StatementImport.idempotency_key == idempotency_key,
        )
    )
    if prior_key:
        if prior_key.content_hash == content_hash:
            return prior_key
        raise HTTPException(status_code=409, detail="This import key was used for another file")
    if session.scalar(
        select(StatementImport.id).where(
            StatementImport.school_id == school_id,
            StatementImport.content_hash == content_hash,
        )
    ):
        raise HTTPException(status_code=409, detail="This statement file was already imported")
    references = [row["source_reference"] for row in rows]
    duplicate = session.scalar(
        select(StatementTransaction.source_reference).where(
            StatementTransaction.school_id == school_id,
            StatementTransaction.source_reference.in_(references),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail=f"Source transaction {duplicate} was already imported"
        )
    learners = _suggestions(session, school_id)
    batch = StatementImport(
        school_id=school_id,
        period_id=period_id,
        file_name=file_name,
        source_type=source_type,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        row_count=len(rows),
        total_amount=sum((row["amount"] for row in rows), Decimal("0")),
        imported_by=context.actor,
    )
    session.add(batch)
    session.flush()
    for row in rows:
        student_id, confidence, reason = _suggest_learner(
            learners, row["source_reference"], row["description"]
        )
        session.add(
            StatementTransaction(
                import_id=batch.id,
                school_id=school_id,
                period_id=period_id,
                channel=source_type,
                status="suggested" if student_id else "unmatched",
                suggested_student_id=student_id,
                confidence=confidence,
                match_reason=reason,
                **row,
            )
        )
    session.add(
        AuditEvent(
            school_id=school_id,
            entity_type="statement_import",
            entity_id=batch.id,
            action="created",
            actor=context.actor,
            summary=f"Imported {batch.row_count} {source_type} transactions from {file_name}",
        )
    )
    return batch


@router.post("/file-imports", status_code=status.HTTP_201_CREATED)
def import_statement_file(
    payload: StatementFileImportCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    context.assert_school(payload.school_id)
    period = resolve_period(
        session, school_id=context.school_id, period_id=payload.period_id, writable=True
    )
    rows = _parse_file(payload.source_type, payload.content)
    content_hash = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    batch = _import_rows(
        session,
        school_id=context.school_id,
        period_id=period.id,
        file_name=payload.file_name.strip(),
        source_type=payload.source_type,
        content_hash=content_hash,
        idempotency_key=payload.idempotency_key,
        rows=rows,
        context=context,
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Statement import duplicates existing data"
        ) from error
    return {"id": batch.id, "row_count": batch.row_count, "total_amount": batch.total_amount}


@router.post("/imports", status_code=status.HTTP_201_CREATED, deprecated=True)
def import_statement(
    payload: StatementImportCreate,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    context.assert_school(payload.school_id)
    period = resolve_period(session, school_id=context.school_id, writable=True)
    rows = [row.model_dump() for row in payload.rows]
    fingerprint = "\n".join(
        f"{row['transaction_date']}|{row['source_reference'].upper()}|{row['amount']}"
        for row in rows
    )
    for row in rows:
        row["source_reference"] = row["source_reference"].strip().upper()
        row["description"] = row["description"].strip()
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    batch = _import_rows(
        session,
        school_id=context.school_id,
        period_id=period.id,
        file_name=payload.file_name.strip(),
        source_type="bank",
        content_hash=digest,
        idempotency_key=f"legacy-{digest[:40]}",
        rows=rows,
        context=context,
    )
    session.commit()
    return {"id": batch.id, "row_count": batch.row_count, "total_amount": batch.total_amount}


@router.get("/transactions")
def list_transactions(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    suggestion = aliased(Student)
    person = aliased(Person)
    rows = session.execute(
        select(StatementTransaction, person)
        .outerjoin(suggestion, suggestion.id == StatementTransaction.suggested_student_id)
        .outerjoin(person, person.id == suggestion.person_id)
        .where(
            StatementTransaction.school_id == school_id,
            StatementTransaction.period_id == period.id,
        )
        .order_by(StatementTransaction.transaction_date.desc(), StatementTransaction.id)
    ).all()
    return [
        {
            "id": item.id,
            "transaction_date": item.transaction_date,
            "source_reference": item.source_reference,
            "description": item.description,
            "amount": item.amount,
            "channel": item.channel,
            "status": item.status,
            "suggested_student_id": item.suggested_student_id,
            "suggested_student_name": (
                f"{person_row.first_name} {person_row.last_name}" if person_row else None
            ),
            "confidence": item.confidence,
            "match_reason": item.match_reason,
            "review_reason": item.review_reason,
            "payment_id": item.payment_id,
            "reversal_payment_id": item.reversal_payment_id,
        }
        for item, person_row in rows
    ]


def _post_reconciled_payment(
    session: Session,
    *,
    transaction: StatementTransaction,
    student: Student,
    context: SchoolContext,
) -> Payment:
    existing = session.scalar(
        select(Payment).where(
            Payment.school_id == context.school_id,
            Payment.external_reference == transaction.source_reference,
        )
    )
    if existing:
        existing_student = session.scalar(
            select(PaymentAllocation.student_id).where(PaymentAllocation.payment_id == existing.id)
        )
        if (
            existing.amount != transaction.amount
            or existing_student != student.id
            or existing.period_id != transaction.period_id
            or existing.transaction_type != "receipt"
        ):
            raise HTTPException(
                status_code=409,
                detail="An existing payment uses this reference with different details",
            )
        transaction.payment_created_by_reconciliation = False
        return existing
    payload = PaymentCreate(
        school_id=context.school_id,
        period_id=transaction.period_id,
        student_id=student.id,
        external_reference=transaction.source_reference,
        channel=transaction.channel,
        amount=transaction.amount,
        note=transaction.description or None,
    )
    allocations = _resolved_allocations(
        session, payload=payload, period_id=transaction.period_id, student=student
    )
    payment = Payment(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=transaction.period_id,
        receipt_no=_next_payment_receipt(session, context.school_id),
        external_reference=transaction.source_reference,
        channel=transaction.channel,
        amount=transaction.amount,
        note=transaction.description or None,
        transaction_type="receipt",
        created_by=context.actor,
    )
    session.add(payment)
    session.flush()
    for allocation in allocations:
        session.add(
            PaymentAllocation(
                payment_id=payment.id,
                student_id=student.id,
                requirement_assignment_id=allocation["requirement_assignment_id"],
                allocation_type=allocation["allocation_type"],
                amount=allocation["amount"],
            )
        )
    session.add_all(
        [
            LedgerEntry(
                school_id=context.school_id,
                period_id=transaction.period_id,
                student_id=student.id,
                entry_type="payment",
                amount=-transaction.amount,
                reference=transaction.source_reference,
                description="Reconciled source collection",
                payment_id=payment.id,
            ),
            StellarAnchor(
                payment_id=payment.id,
                commitment_hash=hashlib.sha256(
                    f"{payment.id}|{transaction.amount}|UGX|{transaction.source_reference}".encode()
                ).hexdigest(),
                status="pending",
            ),
        ]
    )
    transaction.payment_created_by_reconciliation = True
    return payment


@router.post("/transactions/{transaction_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_transaction(
    transaction_id: uuid.UUID,
    payload: ReconciliationConfirm,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    transaction = session.scalar(
        select(StatementTransaction)
        .where(
            StatementTransaction.id == transaction_id,
            StatementTransaction.school_id == context.school_id,
        )
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Statement transaction not found")
    if transaction.status == "reconciled":
        payment = session.get(Payment, transaction.payment_id)
        return {"payment_id": payment.id, "receipt_no": payment.receipt_no}
    if transaction.status not in {"suggested", "unmatched", "unidentified", "rejected"}:
        raise HTTPException(status_code=409, detail="Transaction cannot be reconciled")
    period = resolve_period(
        session,
        school_id=context.school_id,
        period_id=payload.period_id or transaction.period_id,
        writable=True,
    )
    if period.id != transaction.period_id:
        raise HTTPException(status_code=422, detail="Use the statement transaction's period")
    student = session.get(Student, payload.student_id)
    if student is None or student.school_id != transaction.school_id:
        raise HTTPException(status_code=422, detail="Learner does not belong to this school")
    payment = _post_reconciled_payment(
        session, transaction=transaction, student=student, context=context
    )
    transaction.status = "reconciled"
    transaction.suggested_student_id = student.id
    transaction.payment_id = payment.id
    transaction.review_reason = "Human-confirmed learner allocation"
    transaction.reviewed_by = context.actor
    transaction.reviewed_at = datetime.now(UTC)
    _refresh_import_status(session, transaction.import_id)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="statement_transaction",
            entity_id=transaction.id,
            action="reconciled",
            actor=context.actor,
            summary=f"Reconciled {transaction.source_reference} to {student.admission_no}",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Source transaction was already posted"
        ) from error
    return {"payment_id": payment.id, "receipt_no": payment.receipt_no}


@router.post("/transactions/{transaction_id}/decision")
def decide_transaction(
    transaction_id: uuid.UUID,
    payload: ReconciliationDecision,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    transaction = session.scalar(
        select(StatementTransaction).where(
            StatementTransaction.id == transaction_id,
            StatementTransaction.school_id == context.school_id,
        )
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Statement transaction not found")
    if transaction.status in {"reconciled", "reversed"}:
        raise HTTPException(status_code=409, detail="Undo the posted reconciliation first")
    transaction.status = (
        ("suggested" if transaction.suggested_student_id else "unmatched")
        if payload.action == "reopen"
        else payload.action
    )
    transaction.review_reason = payload.reason.strip()
    transaction.reviewed_by = context.actor
    transaction.reviewed_at = datetime.now(UTC)
    _refresh_import_status(session, transaction.import_id)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="statement_transaction",
            entity_id=transaction.id,
            action=payload.action,
            actor=context.actor,
            summary=f"Marked {transaction.source_reference} {transaction.status}: {payload.reason}",
        )
    )
    session.commit()
    return {"id": transaction.id, "status": transaction.status}


@router.post("/transactions/{transaction_id}/undo")
def undo_transaction(
    transaction_id: uuid.UUID,
    payload: ReconciliationUndo,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    if context.role not in {"owner", "bursar"}:
        raise HTTPException(status_code=403, detail="Only an owner or bursar can undo a posting")
    transaction = session.scalar(
        select(StatementTransaction)
        .where(
            StatementTransaction.id == transaction_id,
            StatementTransaction.school_id == context.school_id,
        )
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Statement transaction not found")
    if transaction.status == "reversed" and transaction.reversal_payment_id:
        reversal = session.get(Payment, transaction.reversal_payment_id)
        return {"payment_id": reversal.id, "receipt_no": reversal.receipt_no}
    if transaction.status != "reconciled" or not transaction.payment_id:
        raise HTTPException(status_code=409, detail="Only reconciled transactions can be undone")
    original = session.get(Payment, transaction.payment_id)
    if not transaction.payment_created_by_reconciliation:
        transaction.status = "suggested" if transaction.suggested_student_id else "unmatched"
        transaction.payment_id = None
        transaction.review_reason = payload.reason.strip()
        transaction.reviewed_by = context.actor
        transaction.reviewed_at = datetime.now(UTC)
        _refresh_import_status(session, transaction.import_id)
        session.add(
            AuditEvent(
                school_id=context.school_id,
                entity_type="statement_transaction",
                entity_id=transaction.id,
                action="unlinked",
                actor=context.actor,
                summary=f"Unlinked {transaction.source_reference}: {payload.reason.strip()}",
            )
        )
        session.commit()
        return {"payment_id": None, "receipt_no": None}
    if original is None or original.status != "reconciled":
        raise HTTPException(status_code=409, detail="The linked payment has later corrections")
    resolve_period(
        session, school_id=context.school_id, period_id=transaction.period_id, writable=True
    )
    allocations = session.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == original.id)
    ).all()
    if not allocations:
        raise HTTPException(status_code=409, detail="The linked payment has no allocation evidence")
    reversal = Payment(
        id=uuid.uuid4(),
        school_id=context.school_id,
        period_id=original.period_id,
        receipt_no=_next_payment_receipt(session, context.school_id),
        external_reference=f"UNDO-{transaction.id.hex.upper()}",
        channel=original.channel,
        amount=-original.amount,
        currency=original.currency,
        status="reconciled",
        transaction_type="reversal",
        original_payment_id=original.id,
        correction_reason=payload.reason.strip(),
        idempotency_key=payload.idempotency_key,
        created_by=context.actor,
    )
    session.add(reversal)
    session.flush()
    for allocation in allocations:
        session.add(
            PaymentAllocation(
                payment_id=reversal.id,
                student_id=allocation.student_id,
                requirement_assignment_id=allocation.requirement_assignment_id,
                allocation_type=allocation.allocation_type,
                amount=-allocation.amount,
            )
        )
    session.add_all(
        [
            LedgerEntry(
                school_id=context.school_id,
                period_id=original.period_id,
                student_id=allocations[0].student_id,
                entry_type="reversal",
                amount=original.amount,
                reference=reversal.external_reference,
                description=f"Undo reconciliation {transaction.source_reference}",
                payment_id=reversal.id,
            ),
            StellarAnchor(
                payment_id=reversal.id,
                commitment_hash=hashlib.sha256(
                    f"{reversal.id}|{-original.amount}|UGX|{reversal.external_reference}".encode()
                ).hexdigest(),
                status="pending",
            ),
        ]
    )
    original.status = "reversed"
    transaction.status = "reversed"
    transaction.reversal_payment_id = reversal.id
    transaction.review_reason = payload.reason.strip()
    transaction.reviewed_by = context.actor
    transaction.reviewed_at = datetime.now(UTC)
    _refresh_import_status(session, transaction.import_id)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="statement_transaction",
            entity_id=transaction.id,
            action="reversed",
            actor=context.actor,
            summary=f"Undid {transaction.source_reference}: {payload.reason.strip()}",
        )
    )
    session.commit()
    return {"payment_id": reversal.id, "receipt_no": reversal.receipt_no}


def _batch_payload(session: Session, batch: CashierCollectionBatch) -> dict:
    receipt_count = session.scalar(
        select(func.count(CashierBatchPayment.id)).where(CashierBatchPayment.batch_id == batch.id)
    )
    return {
        "id": batch.id,
        "period_id": batch.period_id,
        "business_date": batch.business_date,
        "cashier_actor": batch.cashier_actor,
        "status": batch.status,
        "expected_cash": batch.expected_cash,
        "counted_cash": batch.counted_cash,
        "variance": batch.variance,
        "deposit_amount": batch.deposit_amount,
        "deposit_reference": batch.deposit_reference,
        "cashier_note": batch.cashier_note,
        "supervisor_note": batch.supervisor_note,
        "signed_off_by": batch.signed_off_by,
        "receipt_count": receipt_count or 0,
    }


@router.get("/cash-batches")
def list_cash_batches(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    query = select(CashierCollectionBatch).where(
        CashierCollectionBatch.school_id == school_id,
        CashierCollectionBatch.period_id == period.id,
    )
    if context.role == "cashier":
        query = query.where(CashierCollectionBatch.cashier_actor == context.actor)
    batches = session.scalars(query.order_by(CashierCollectionBatch.business_date.desc())).all()
    return [_batch_payload(session, batch) for batch in batches]


@router.post("/cash-batches", status_code=status.HTTP_201_CREATED)
def open_cash_batch(
    payload: CashBatchOpen,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    context.assert_school(payload.school_id)
    if payload.business_date > datetime.now(KAMPALA).date():
        raise HTTPException(status_code=422, detail="A cash-up date cannot be in the future")
    period = resolve_period(
        session, school_id=context.school_id, period_id=payload.period_id, writable=True
    )
    existing = session.scalar(
        select(CashierCollectionBatch).where(
            CashierCollectionBatch.school_id == context.school_id,
            CashierCollectionBatch.period_id == period.id,
            CashierCollectionBatch.cashier_actor == context.actor,
            CashierCollectionBatch.business_date == payload.business_date,
        )
    )
    if existing:
        return _batch_payload(session, existing)
    batch = CashierCollectionBatch(
        school_id=context.school_id,
        period_id=period.id,
        business_date=payload.business_date,
        cashier_actor=context.actor,
    )
    session.add(batch)
    session.commit()
    return _batch_payload(session, batch)


@router.post("/cash-batches/{batch_id}/submit")
def submit_cash_batch(
    batch_id: uuid.UUID,
    payload: CashBatchSubmit,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("payments:write")),
):
    batch = session.scalar(
        select(CashierCollectionBatch)
        .where(
            CashierCollectionBatch.id == batch_id,
            CashierCollectionBatch.school_id == context.school_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Cash batch not found")
    if batch.cashier_actor != context.actor:
        raise HTTPException(status_code=403, detail="Only the collecting cashier can submit")
    if batch.status == "signed_off":
        raise HTTPException(status_code=409, detail="This cash-up is already signed off")
    if batch.status == "submitted" and batch.idempotency_key == payload.idempotency_key:
        if (
            batch.counted_cash == payload.counted_cash
            and batch.deposit_amount == payload.deposit_amount
            and (batch.deposit_reference or "") == (payload.deposit_reference or "").strip()
            and (batch.cashier_note or "") == (payload.note or "").strip()
        ):
            return _batch_payload(session, batch)
        raise HTTPException(status_code=409, detail="This cash-up key was used with other totals")
    if payload.deposit_amount and not (payload.deposit_reference or "").strip():
        raise HTTPException(status_code=422, detail="A deposit reference is required")
    if payload.deposit_amount > payload.counted_cash:
        raise HTTPException(status_code=422, detail="Deposit cannot exceed counted cash")
    local_start = datetime.combine(batch.business_date, time.min, tzinfo=KAMPALA)
    utc_start = local_start.astimezone(UTC)
    utc_end = (local_start + timedelta(days=1)).astimezone(UTC)
    linked_payment_ids = select(CashierBatchPayment.payment_id)
    payments = session.scalars(
        select(Payment).where(
            Payment.school_id == context.school_id,
            Payment.period_id == batch.period_id,
            Payment.channel == "cash",
            Payment.created_by == batch.cashier_actor,
            Payment.received_at >= utc_start,
            Payment.received_at < utc_end,
            Payment.id.notin_(linked_payment_ids),
        )
    ).all()
    for payment in payments:
        session.add(
            CashierBatchPayment(batch_id=batch.id, payment_id=payment.id, amount=payment.amount)
        )
    session.flush()
    expected = session.scalar(
        select(func.coalesce(func.sum(CashierBatchPayment.amount), 0)).where(
            CashierBatchPayment.batch_id == batch.id
        )
    ) or Decimal("0")
    batch.expected_cash = expected
    batch.counted_cash = payload.counted_cash
    batch.variance = payload.counted_cash - expected
    batch.deposit_amount = payload.deposit_amount
    batch.deposit_reference = (
        payload.deposit_reference.strip() if payload.deposit_reference else None
    )
    batch.cashier_note = payload.note.strip() if payload.note else None
    batch.idempotency_key = payload.idempotency_key
    batch.status = "submitted"
    batch.submitted_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="cashier_collection_batch",
            entity_id=batch.id,
            action="submitted",
            actor=context.actor,
            summary=f"Submitted cash-up with variance {batch.variance} UGX",
        )
    )
    session.commit()
    return _batch_payload(session, batch)


@router.post("/cash-batches/{batch_id}/decision")
def decide_cash_batch(
    batch_id: uuid.UUID,
    payload: CashBatchDecision,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:write")),
):
    if context.role not in {"owner", "bursar"}:
        raise HTTPException(status_code=403, detail="Only an owner or bursar can sign off")
    batch = session.scalar(
        select(CashierCollectionBatch).where(
            CashierCollectionBatch.id == batch_id,
            CashierCollectionBatch.school_id == context.school_id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Cash batch not found")
    if batch.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted cash-ups can be reviewed")
    control_difference = batch.variance or batch.counted_cash - batch.deposit_amount
    if payload.action == "approve" and control_difference and not (payload.note or "").strip():
        raise HTTPException(status_code=422, detail="Explain the approved cash or deposit variance")
    batch.status = "signed_off" if payload.action == "approve" else "returned"
    batch.supervisor_note = payload.note.strip() if payload.note else None
    if payload.action == "approve":
        batch.signed_off_by = context.actor
        batch.signed_off_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            school_id=context.school_id,
            entity_type="cashier_collection_batch",
            entity_id=batch.id,
            action="signed_off" if payload.action == "approve" else "returned",
            actor=context.actor,
            summary=f"{payload.action.title()} cash-up for {batch.cashier_actor}",
        )
    )
    session.commit()
    return _batch_payload(session, batch)


@router.get("/summary")
def reconciliation_summary(
    school_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    context: SchoolContext = Depends(require_permission("reconciliation:read")),
):
    context.assert_school(school_id)
    period = resolve_period(session, school_id=school_id, period_id=period_id)
    source_rows = session.execute(
        select(
            StatementTransaction.channel,
            StatementTransaction.status,
            func.count(StatementTransaction.id),
            func.coalesce(func.sum(StatementTransaction.amount), 0),
        )
        .where(
            StatementTransaction.school_id == school_id,
            StatementTransaction.period_id == period.id,
        )
        .group_by(StatementTransaction.channel, StatementTransaction.status)
    ).all()
    cash_rows = session.execute(
        select(
            CashierCollectionBatch.status,
            func.count(CashierCollectionBatch.id),
            func.coalesce(func.sum(CashierCollectionBatch.expected_cash), 0),
            func.coalesce(func.sum(CashierCollectionBatch.counted_cash), 0),
            func.coalesce(func.sum(CashierCollectionBatch.variance), 0),
            func.coalesce(func.sum(CashierCollectionBatch.deposit_amount), 0),
        )
        .where(
            CashierCollectionBatch.school_id == school_id,
            CashierCollectionBatch.period_id == period.id,
        )
        .group_by(CashierCollectionBatch.status)
    ).all()
    return {
        "period_id": period.id,
        "sources": [
            {"channel": channel, "status": row_status, "count": count, "amount": amount}
            for channel, row_status, count, amount in source_rows
        ],
        "cash_up": [
            {
                "status": row_status,
                "count": count,
                "expected": expected,
                "counted": counted,
                "variance": variance,
                "deposited": deposited,
            }
            for row_status, count, expected, counted, variance, deposited in cash_rows
        ],
    }
