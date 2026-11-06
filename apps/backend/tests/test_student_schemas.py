import uuid

import pytest
from pydantic import ValidationError

from harambeeone_api.academic_structure import template_classes
from harambeeone_api.schemas import ClassWrite, SchoolCreate, SchoolOnboardingCreate, StudentCreate


def registration_payload() -> dict:
    return {
        "school_id": uuid.uuid4(),
        "first_name": "Amina",
        "last_name": "Tendo",
        "gender": "female",
        "class_id": uuid.uuid4(),
        "fee_structure_id": uuid.uuid4(),
        "academic_year": 2026,
        "term": 2,
        "guardians": [
            {
                "first_name": "Halima",
                "last_name": "Nansubuga",
                "relationship": "mother",
                "phone": "+256700000000",
                "is_primary": True,
            }
        ],
    }


def test_registration_accepts_one_primary_guardian() -> None:
    student = StudentCreate.model_validate(registration_payload())

    assert student.guardians[0].is_primary is True


def test_registration_rejects_multiple_primary_guardians() -> None:
    payload = registration_payload()
    payload["guardians"].append({**payload["guardians"][0], "phone": "+256711111111"})

    with pytest.raises(ValidationError, match="Exactly one guardian must be primary"):
        StudentCreate.model_validate(payload)


def test_class_stream_names_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="Stream names must be unique"):
        ClassWrite(name="P.4", level="primary", sort_order=7, streams=["East", "east"])


def test_class_can_have_no_streams() -> None:
    academic_class = ClassWrite(name="P.4", level="primary", canonical_code="P4", sort_order=7)

    assert academic_class.streams == []


def test_day_care_creates_no_academic_classes() -> None:
    school = SchoolCreate(name="Bright Start", programme_codes=["day_care"])

    assert template_classes(school.programme_codes) == []


def test_day_care_child_can_be_registered_without_class_or_fee() -> None:
    payload = registration_payload()
    payload["class_id"] = None
    payload["fee_structure_id"] = None

    student = StudentCreate.model_validate(payload)

    assert student.class_id is None
    assert student.fee_structure_id is None


def test_combined_school_template_uses_uganda_grade_codes() -> None:
    rows = template_classes(["pre_primary", "primary", "lower_secondary", "upper_secondary"])

    assert [row[0] for row in rows] == [
        "BABY",
        "MIDDLE",
        "TOP",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
    ]


def test_school_profile_accepts_a_primary_school_that_stops_before_p7() -> None:
    school = SchoolCreate(
        name="Growing Junior School",
        programme_codes=["primary"],
        canonical_codes=["P1", "P2", "P3", "P4", "P5"],
    )

    assert school.canonical_codes == ["P1", "P2", "P3", "P4", "P5"]


def test_school_profile_rejects_classes_from_unselected_programmes() -> None:
    with pytest.raises(ValidationError, match="Classes do not belong"):
        SchoolCreate(
            name="Primary Only School",
            programme_codes=["primary"],
            canonical_codes=["P1", "S1"],
        )


def test_onboarding_creates_one_operational_section() -> None:
    primary = SchoolOnboardingCreate(
        name="Primary Section",
        programme_codes=["primary"],
        canonical_codes=["P1", "P2"],
    )
    full_secondary = SchoolOnboardingCreate(
        name="Secondary Section",
        programme_codes=["lower_secondary", "upper_secondary"],
        canonical_codes=["S1", "S6"],
    )

    assert primary.programme_codes == ["primary"]
    assert full_secondary.programme_codes == ["lower_secondary", "upper_secondary"]


def test_onboarding_rejects_combined_primary_and_secondary_workspace() -> None:
    with pytest.raises(ValidationError, match="one bursar workspace per school section"):
        SchoolOnboardingCreate(
            name="Combined School",
            programme_codes=["primary", "lower_secondary"],
            canonical_codes=["P1", "S1"],
        )
