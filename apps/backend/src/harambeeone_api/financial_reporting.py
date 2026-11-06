import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from harambeeone_api.models import AcademicPeriod, AcademicYear, LedgerEntry

CREDIT_ENTRY_TYPES = frozenset(
    {"discount", "sponsorship_credit", "waiver", "period_correction_credit"}
)
BALANCE_FORWARD_ENTRY_TYPES = frozenset({"opening_balance", "carried_balance", "carry_correction"})
ZERO = Decimal("0")


@dataclass(frozen=True)
class FinancialTotals:
    opening_balance: Decimal = ZERO
    charges: Decimal = ZERO
    credits: Decimal = ZERO
    payments: Decimal = ZERO
    refunds: Decimal = ZERO
    reversals: Decimal = ZERO
    assessment_adjustments: Decimal = ZERO
    net_assessed: Decimal = ZERO
    net_collected: Decimal = ZERO
    period_activity: Decimal = ZERO
    closing_balance: Decimal = ZERO

    @property
    def outstanding(self) -> Decimal:
        return max(self.closing_balance, ZERO)

    @property
    def credit_balance(self) -> Decimal:
        return max(-self.closing_balance, ZERO)


def _summarize_groups(
    groups: Iterable[tuple[str, bool, Decimal]], *, prior_balance: Decimal = ZERO
) -> FinancialTotals:
    charges = ZERO
    credits = ZERO
    payments = ZERO
    refunds = ZERO
    reversals = ZERO
    assessment_adjustments = ZERO
    payment_corrections = ZERO
    carried_balance = ZERO
    has_carried_balance = False

    for entry_type, payment_linked, raw_amount in groups:
        amount = Decimal(raw_amount or ZERO)
        if entry_type in BALANCE_FORWARD_ENTRY_TYPES:
            carried_balance += amount
            has_carried_balance = True
        elif entry_type in CREDIT_ENTRY_TYPES:
            credits -= amount
        elif entry_type == "payment":
            payments -= amount
        elif entry_type == "refund":
            refunds += amount
            if payment_linked:
                payment_corrections += amount
            else:
                assessment_adjustments += amount
        elif entry_type == "reversal":
            reversals += amount
            if payment_linked:
                payment_corrections += amount
            else:
                assessment_adjustments += amount
        else:
            charges += amount

    opening_balance = carried_balance if has_carried_balance else Decimal(prior_balance or ZERO)
    net_assessed = charges - credits + assessment_adjustments
    net_collected = payments - payment_corrections
    period_activity = net_assessed - net_collected
    return FinancialTotals(
        opening_balance=opening_balance,
        charges=charges,
        credits=credits,
        payments=payments,
        refunds=refunds,
        reversals=reversals,
        assessment_adjustments=assessment_adjustments,
        net_assessed=net_assessed,
        net_collected=net_collected,
        period_activity=period_activity,
        closing_balance=opening_balance + period_activity,
    )


def summarize_ledger_entries(
    entries: Iterable[LedgerEntry], *, prior_balance: Decimal = ZERO
) -> FinancialTotals:
    grouped: dict[tuple[str, bool], Decimal] = defaultdict(lambda: ZERO)
    for entry in entries:
        grouped[(entry.entry_type, entry.payment_id is not None)] += entry.amount
    return _summarize_groups(
        (
            (entry_type, payment_linked, amount)
            for (entry_type, payment_linked), amount in grouped.items()
        ),
        prior_balance=prior_balance,
    )


def _prior_period_ids(session: Session, period: AcademicPeriod) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(AcademicPeriod.id)
            .join(AcademicYear, AcademicYear.id == AcademicPeriod.academic_year_id)
            .where(
                AcademicPeriod.school_id == period.school_id,
                (AcademicYear.year < period.academic_year.year)
                | (
                    (AcademicYear.year == period.academic_year.year)
                    & (AcademicPeriod.sequence < period.sequence)
                ),
            )
        ).all()
    )


def load_learner_financial_totals(
    session: Session, *, period: AcademicPeriod
) -> dict[uuid.UUID, FinancialTotals]:
    prior_ids = _prior_period_ids(session, period)
    prior_by_student = (
        dict(
            session.execute(
                select(LedgerEntry.student_id, func.coalesce(func.sum(LedgerEntry.amount), 0))
                .where(
                    LedgerEntry.school_id == period.school_id,
                    LedgerEntry.period_id.in_(prior_ids),
                )
                .group_by(LedgerEntry.student_id)
            ).all()
        )
        if prior_ids
        else {}
    )
    current_groups: dict[uuid.UUID, list[tuple[str, bool, Decimal]]] = defaultdict(list)
    for student_id, entry_type, payment_linked, amount in session.execute(
        select(
            LedgerEntry.student_id,
            LedgerEntry.entry_type,
            LedgerEntry.payment_id.is_not(None),
            func.coalesce(func.sum(LedgerEntry.amount), 0),
        )
        .where(
            LedgerEntry.school_id == period.school_id,
            LedgerEntry.period_id == period.id,
        )
        .group_by(
            LedgerEntry.student_id,
            LedgerEntry.entry_type,
            LedgerEntry.payment_id.is_not(None),
        )
    ):
        current_groups[student_id].append((entry_type, payment_linked, amount))

    student_ids = set(prior_by_student) | set(current_groups)
    return {
        student_id: _summarize_groups(
            current_groups.get(student_id, ()),
            prior_balance=prior_by_student.get(student_id, ZERO),
        )
        for student_id in student_ids
    }


def aggregate_financial_totals(
    totals: Iterable[FinancialTotals],
) -> FinancialTotals:
    rows = list(totals)
    fields = FinancialTotals.__dataclass_fields__
    values = {field: sum((getattr(row, field) for row in rows), ZERO) for field in fields}
    return FinancialTotals(**values)


def load_school_financial_totals(session: Session, *, period: AcademicPeriod) -> FinancialTotals:
    return aggregate_financial_totals(
        load_learner_financial_totals(session, period=period).values()
    )


def load_student_financial_totals(
    session: Session, *, period: AcademicPeriod, student_id: uuid.UUID
) -> FinancialTotals:
    return load_learner_financial_totals(session, period=period).get(student_id, FinancialTotals())
