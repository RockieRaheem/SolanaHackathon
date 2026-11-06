import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from harambeeone_api.models import Requirement, StudentRequirement
from harambeeone_api.requirements import requirement_status
from harambeeone_api.schemas import RequirementCreate


def requirement_payload(requirement_type: str = "school_item") -> dict:
    return {
        "school_id": uuid.uuid4(),
        "name": "Candidate T-shirt",
        "code": "s4-shirt",
        "requirement_type": requirement_type,
        "academic_year": 2026,
        "term": 3,
        "amount": 30_000 if requirement_type in {"payment", "school_item"} else 0,
        "quantity": 1,
        "unit": "shirt",
        "class_ids": [uuid.uuid4()],
    }


def test_payable_requirement_requires_positive_amount() -> None:
    payload = requirement_payload()
    payload["amount"] = 0

    with pytest.raises(ValidationError, match="amount greater than zero"):
        RequirementCreate.model_validate(payload)


def test_brought_item_cannot_create_cash_charge() -> None:
    payload = requirement_payload("bring_item")
    payload["amount"] = 5_000

    with pytest.raises(ValidationError, match="cannot have a cash amount"):
        RequirementCreate.model_validate(payload)


def test_school_item_is_paid_before_it_is_issued() -> None:
    requirement = Requirement(
        id=uuid.uuid4(),
        school_id=uuid.uuid4(),
        name="Uniform",
        code="UNI",
        requirement_type="school_item",
        academic_year=2026,
        term=1,
        amount=Decimal("80000"),
        quantity=Decimal("1"),
        unit="set",
    )
    assignment = StudentRequirement(
        id=uuid.uuid4(),
        requirement_id=requirement.id,
        student_id=uuid.uuid4(),
        expected_amount=Decimal("80000"),
        expected_quantity=Decimal("1"),
        fulfilled_quantity=Decimal("0"),
    )

    assert requirement_status(assignment, requirement, Decimal("40000")) == "partially_paid"
    assert requirement_status(assignment, requirement, Decimal("80000")) == "paid"
    assignment.fulfilled_quantity = Decimal("1")
    assert requirement_status(assignment, requirement, Decimal("80000")) == "issued"
