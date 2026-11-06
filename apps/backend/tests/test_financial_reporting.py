import uuid
from decimal import Decimal

from harambeeone_api.financial_reporting import (
    aggregate_financial_totals,
    summarize_ledger_entries,
)
from harambeeone_api.models import LedgerEntry


def entry(entry_type: str, amount: str, *, payment_linked: bool = False) -> LedgerEntry:
    return LedgerEntry(
        entry_type=entry_type,
        amount=Decimal(amount),
        payment_id=uuid.uuid4() if payment_linked else None,
    )


def test_financial_equation_classifies_every_ledger_direction() -> None:
    totals = summarize_ledger_entries(
        [
            entry("fee_charge", "200"),
            entry("requirement_charge", "30"),
            entry("discount", "-20"),
            entry("payment", "-100", payment_linked=True),
            entry("refund", "10"),
            entry("reversal", "-5"),
        ],
        prior_balance=Decimal("60"),
    )

    assert totals.charges == Decimal("230")
    assert totals.credits == Decimal("20")
    assert totals.payments == Decimal("100")
    assert totals.refunds == Decimal("10")
    assert totals.reversals == Decimal("-5")
    assert totals.net_assessed == Decimal("215")
    assert totals.net_collected == Decimal("100")
    assert totals.period_activity == Decimal("115")
    assert totals.closing_balance == Decimal("175")
    assert totals.outstanding == Decimal("175")
    assert totals.credit_balance == Decimal("0")


def test_payment_corrections_reduce_net_collections_without_changing_assessment() -> None:
    totals = summarize_ledger_entries(
        [
            entry("fee_charge", "100"),
            entry("payment", "-100", payment_linked=True),
            entry("refund", "15", payment_linked=True),
            entry("reversal", "5", payment_linked=True),
        ]
    )

    assert totals.net_assessed == Decimal("100")
    assert totals.net_collected == Decimal("80")
    assert totals.period_activity == Decimal("20")
    assert totals.closing_balance == Decimal("20")


def test_explicit_carried_balance_replaces_legacy_derived_opening() -> None:
    totals = summarize_ledger_entries(
        [entry("carried_balance", "60"), entry("fee_charge", "100")],
        prior_balance=Decimal("999"),
    )

    assert totals.opening_balance == Decimal("60")
    assert totals.period_activity == Decimal("100")
    assert totals.closing_balance == Decimal("160")


def test_aggregate_totals_preserves_the_financial_equation() -> None:
    first = summarize_ledger_entries([entry("fee_charge", "100")])
    second = summarize_ledger_entries(
        [entry("fee_charge", "50"), entry("payment", "-20", payment_linked=True)]
    )
    totals = aggregate_financial_totals([first, second])

    assert totals.net_assessed == Decimal("150")
    assert totals.net_collected == Decimal("20")
    assert totals.closing_balance == Decimal("130")


def test_financial_equation_balances_at_learner_class_and_school_levels() -> None:
    learner_rows = {
        "P7": [
            summarize_ledger_entries(
                [
                    entry("fee_charge", "500"),
                    entry("discount", "-50"),
                    entry("payment", "-200", payment_linked=True),
                ],
                prior_balance=Decimal("100"),
            ),
            summarize_ledger_entries(
                [
                    entry("requirement_charge", "120"),
                    entry("payment", "-80", payment_linked=True),
                ]
            ),
        ],
        "S4": [
            summarize_ledger_entries(
                [entry("fee_charge", "300"), entry("waiver", "-25")],
                prior_balance=Decimal("-20"),
            )
        ],
    }

    for learners in learner_rows.values():
        for learner in learners:
            assert learner.opening_balance + learner.net_assessed - learner.net_collected == (
                learner.closing_balance
            )

    class_totals = {
        class_code: aggregate_financial_totals(learners)
        for class_code, learners in learner_rows.items()
    }
    for totals in class_totals.values():
        assert totals.opening_balance + totals.net_assessed - totals.net_collected == (
            totals.closing_balance
        )

    school_totals = aggregate_financial_totals(class_totals.values())
    assert school_totals.opening_balance == Decimal("80")
    assert school_totals.net_assessed == Decimal("845")
    assert school_totals.net_collected == Decimal("280")
    assert school_totals.closing_balance == Decimal("645")
    assert school_totals.opening_balance + school_totals.net_assessed - (
        school_totals.net_collected
    ) == school_totals.closing_balance
