from datetime import date
from decimal import Decimal

from harambeeone_api.finance import _overdue_position


def test_overdue_position_applies_payments_to_oldest_installment() -> None:
    events = [
        (date(2026, 2, 1), Decimal("300")),
        (date(2026, 1, 1), Decimal("500")),
        (date(2026, 3, 1), Decimal("200")),
    ]

    amount, overdue_since = _overdue_position(events, Decimal("650"), date(2026, 3, 15))

    assert amount == Decimal("350")
    assert overdue_since == date(2026, 2, 1)


def test_overdue_position_excludes_future_installments() -> None:
    events = [(date(2026, 10, 1), Decimal("500"))]

    amount, overdue_since = _overdue_position(events, Decimal("0"), date(2026, 9, 1))

    assert amount == Decimal("0")
    assert overdue_since is None
