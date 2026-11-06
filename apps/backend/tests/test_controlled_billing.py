import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from harambeeone_api.auth import AuthenticatedUser, get_current_user
from harambeeone_api.database import Base, get_session
from harambeeone_api.main import app
from harambeeone_api.models import (
    AcademicClass,
    AcademicPeriod,
    AcademicYear,
    Enrollment,
    FeeCategory,
    FeeStructure,
    LedgerEntry,
    Person,
    Requirement,
    School,
    SchoolMembership,
    Stream,
    Student,
    StudentFeeAssignment,
    StudentRequirement,
)


@pytest.fixture
def billing_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    with Session(engine) as session:
        school = School(name="Billing School")
        other_school = School(name="Other School")
        session.add_all([school, other_school])
        session.flush()
        academic_year = AcademicYear(
            school_id=school.id,
            name="2027 Academic Year",
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status="open",
        )
        session.add(academic_year)
        session.flush()
        period = AcademicPeriod(
            academic_year_id=academic_year.id,
            school_id=school.id,
            name="Term 1",
            sequence=1,
            opening_date=date(2027, 1, 10),
            due_date=date(2027, 2, 10),
            closing_date=date(2027, 4, 20),
            status="open",
        )
        primary = AcademicClass(
            school_id=school.id,
            name="Primary Seven",
            level="primary",
            canonical_code="P7",
            sort_order=7,
        )
        secondary = AcademicClass(
            school_id=school.id,
            name="Senior Four",
            level="lower_secondary",
            canonical_code="S4",
            sort_order=11,
        )
        session.add_all([period, primary, secondary])
        session.flush()
        east = Stream(class_id=primary.id, name="East")
        west = Stream(class_id=primary.id, name="West")
        category = FeeCategory(
            school_id=school.id,
            name="Tuition",
            code="TUIT",
            category_type="tuition",
            priority=1,
        )
        session.add_all([east, west, category])
        session.flush()
        learners = []
        placements = [
            ("Day", "Learner", primary.id, east.id, "day"),
            ("Boarding", "Learner", primary.id, west.id, "boarding"),
            ("Candidate", "Learner", secondary.id, None, "day"),
        ]
        for index, (first, last, class_id, stream_id, boarding) in enumerate(placements, 1):
            person = Person(first_name=first, last_name=last)
            session.add(person)
            session.flush()
            learner = Student(
                school_id=school.id,
                person_id=person.id,
                admission_no=f"BILL-{index:03d}",
                gender="female",
                boarding_status=boarding,
            )
            session.add(learner)
            session.flush()
            session.add(
                Enrollment(
                    student_id=learner.id,
                    class_id=class_id,
                    stream_id=stream_id,
                    period_id=period.id,
                    academic_year=2027,
                    term=1,
                )
            )
            learners.append(learner.id)
        session.add(SchoolMembership(school_id=school.id, auth_user_id=user_id, role="owner"))
        session.commit()
        ids = {
            "school": school.id,
            "other_school": other_school.id,
            "period": period.id,
            "primary": primary.id,
            "secondary": secondary.id,
            "east": east.id,
            "category": category.id,
            "learners": learners,
        }

    def session_override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email="owner@example.com"
    )
    try:
        yield engine, user_id, ids, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_plan(
    client: TestClient,
    ids: dict,
    *,
    name: str,
    class_id: uuid.UUID,
    total: int,
    boarding_status: str | None = None,
    stream_id: uuid.UUID | None = None,
) -> str:
    response = client.post(
        "/api/v1/fee-plans",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "class_id": str(class_id),
            "stream_id": str(stream_id) if stream_id else None,
            "name": name,
            "academic_year": 2027,
            "term": 1,
            "currency": "UGX",
            "target_type": "cohort",
            "boarding_status": boarding_status,
            "items": [{"category_id": str(ids["category"]), "amount": total}],
            "installments": [
                {
                    "name": "Opening",
                    "calculation_type": "percentage",
                    "percentage": 60,
                    "due_date": "2027-02-01",
                    "sort_order": 1,
                },
                {
                    "name": "Balance",
                    "calculation_type": "percentage",
                    "percentage": 40,
                    "due_date": "2027-03-01",
                    "sort_order": 2,
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_empty_class_with_only_draft_billing_can_be_deleted(billing_workspace) -> None:
    engine, _user_id, ids, client = billing_workspace
    created = client.post(
        f"/api/v1/schools/{ids['school']}/classes",
        json={
            "name": "Primary Six",
            "level": "primary",
            "canonical_code": "P6",
            "sort_order": 6,
            "streams": [],
        },
    )
    assert created.status_code == 201, created.text
    class_id = created.json()["id"]
    plan_id = create_plan(
        client,
        ids,
        name="Unused P6 fees",
        class_id=uuid.UUID(class_id),
        total=120_000,
    )
    requirement = client.post(
        "/api/v1/requirements",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "name": "Unused P6 uniform",
            "code": "P6-UNUSED",
            "requirement_type": "school_item",
            "academic_year": 2027,
            "term": 1,
            "amount": 30_000,
            "quantity": 1,
            "unit": "set",
            "is_mandatory": True,
            "class_ids": [class_id],
        },
    )
    assert requirement.status_code == 201, requirement.text

    rows = client.get(f"/api/v1/schools/{ids['school']}/classes")
    assert rows.status_code == 200, rows.text
    empty_class = next(row for row in rows.json() if row["id"] == class_id)
    assert empty_class["student_count"] == 0
    assert empty_class["draft_fee_count"] == 1
    assert empty_class["draft_requirement_count"] == 1
    assert empty_class["can_delete"] is True

    removed = client.delete(f"/api/v1/classes/{class_id}")
    assert removed.status_code == 204, removed.text
    with Session(engine) as session:
        assert session.get(AcademicClass, uuid.UUID(class_id)) is None
        assert session.get(FeeStructure, uuid.UUID(plan_id)) is None
        assert session.get(Requirement, uuid.UUID(requirement.json()["id"])) is None


def test_class_with_learner_history_cannot_be_deleted(billing_workspace) -> None:
    _engine, _user_id, ids, client = billing_workspace

    removed = client.delete(f"/api/v1/classes/{ids['primary']}")

    assert removed.status_code == 409
    assert "historical learner placement" in removed.json()["detail"]


def test_preview_publish_is_atomic_exact_and_idempotent(billing_workspace) -> None:
    engine, _user_id, ids, client = billing_workspace
    create_plan(
        client,
        ids,
        name="P7 day fees",
        class_id=ids["primary"],
        total=100_000,
        boarding_status="day",
    )
    create_plan(
        client,
        ids,
        name="P7 boarding fees",
        class_id=ids["primary"],
        total=150_000,
        boarding_status="boarding",
    )
    create_plan(
        client,
        ids,
        name="S4 candidate fees",
        class_id=ids["secondary"],
        total=80_000,
    )
    physical = client.post(
        "/api/v1/requirements",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "name": "Candidate examination card",
            "code": "S4-CARD",
            "requirement_type": "document",
            "academic_year": 2027,
            "term": 1,
            "amount": 0,
            "quantity": 1,
            "unit": "card",
            "is_mandatory": True,
            "class_ids": [str(ids["secondary"])],
        },
    )
    assert physical.status_code == 201, physical.text
    optional = client.post(
        "/api/v1/requirements",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "name": "Candidate uniform",
            "code": "S4-UNIFORM",
            "requirement_type": "school_item",
            "academic_year": 2027,
            "term": 1,
            "amount": 30_000,
            "quantity": 1,
            "unit": "set",
            "is_mandatory": False,
            "class_ids": [str(ids["secondary"])],
            "student_ids": [str(ids["learners"][2])],
        },
    )
    assert optional.status_code == 201, optional.text
    adjustment = client.post(
        "/api/v1/billing/adjustments",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "student_id": str(ids["learners"][0]),
            "category_id": str(ids["category"]),
            "adjustment_type": "discount",
            "amount": 10_000,
            "description": "Sibling discount",
            "reason": "Approved school sibling policy",
        },
    )
    assert adjustment.status_code == 201, adjustment.text

    query = f"school_id={ids['school']}&period_id={ids['period']}"
    preview_response = client.get(f"/api/v1/billing/preview?{query}")
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["can_publish"] is True
    assert preview["summary"] == {
        "learner_count": 3,
        "fee_assignment_count": 3,
        "requirement_assignment_count": 2,
        "adjustment_count": 1,
        "charge_total": "360000.00",
        "credit_total": "10000.00",
        "net_total": "350000.00",
    }
    assert preview["conflicts"] == []

    payload = {
        "school_id": str(ids["school"]),
        "period_id": str(ids["period"]),
        "preview_token": preview["preview_token"],
        "idempotency_key": "term-one-2027-v1",
    }
    published = client.post("/api/v1/billing/publish", json=payload)
    assert published.status_code == 201, published.text
    assert published.json()["net_total"] == "350000.00"
    assert published.json()["replayed"] is False
    replayed = client.post("/api/v1/billing/publish", json=payload)
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["replayed"] is True

    with Session(engine) as session:
        assert session.scalar(select(func.count(StudentFeeAssignment.id))) == 3
        assert session.scalar(select(func.count(StudentRequirement.id))) == 2
        assert session.scalar(select(func.count(LedgerEntry.id))) == 5
        school_total = session.scalar(
            select(func.sum(LedgerEntry.amount)).where(
                LedgerEntry.school_id == ids["school"],
                LedgerEntry.period_id == ids["period"],
            )
        )
        assert school_total == Decimal("350000.00")
        learner_totals = dict(
            session.execute(
                select(LedgerEntry.student_id, func.sum(LedgerEntry.amount)).group_by(
                    LedgerEntry.student_id
                )
            ).all()
        )
        assert learner_totals[ids["learners"][0]] == Decimal("90000.00")
        assert learner_totals[ids["learners"][1]] == Decimal("150000.00")
        assert learner_totals[ids["learners"][2]] == Decimal("110000.00")
        class_totals = dict(
            session.execute(
                select(Enrollment.class_id, func.sum(LedgerEntry.amount))
                .join(
                    LedgerEntry,
                    and_(
                        LedgerEntry.student_id == Enrollment.student_id,
                        LedgerEntry.period_id == Enrollment.period_id,
                    ),
                )
                .where(Enrollment.period_id == ids["period"])
                .group_by(Enrollment.class_id)
            ).all()
        )
        assert class_totals[ids["primary"]] == Decimal("240000.00")
        assert class_totals[ids["secondary"]] == Decimal("110000.00")

    empty_preview = client.get(f"/api/v1/billing/preview?{query}").json()
    assert empty_preview["can_publish"] is False
    assert empty_preview["summary"]["net_total"] == "0.00"


def test_conflicts_and_stale_previews_cannot_post(billing_workspace) -> None:
    engine, _user_id, ids, client = billing_workspace
    create_plan(
        client,
        ids,
        name="Primary standard",
        class_id=ids["primary"],
        total=100_000,
    )
    query = f"school_id={ids['school']}&period_id={ids['period']}"
    clean_preview = client.get(f"/api/v1/billing/preview?{query}").json()
    override_id = create_plan(
        client,
        ids,
        name="East stream override",
        class_id=ids["primary"],
        stream_id=ids["east"],
        total=90_000,
    )
    conflict_preview = client.get(f"/api/v1/billing/preview?{query}").json()
    assert len(conflict_preview["conflicts"]) == 1
    assert conflict_preview["can_publish"] is False
    stale = client.post(
        "/api/v1/billing/publish",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "preview_token": clean_preview["preview_token"],
            "idempotency_key": "stale-preview-test",
        },
    )
    assert stale.status_code == 409
    with Session(engine) as session:
        assert session.scalar(select(func.count(LedgerEntry.id))) == 0
        assert session.scalar(select(func.count(StudentFeeAssignment.id))) == 0
    removed = client.delete(f"/api/v1/fee-plans/{override_id}")
    assert removed.status_code == 204, removed.text
    resolved = client.get(f"/api/v1/billing/preview?{query}").json()
    assert resolved["conflicts"] == []
    assert resolved["can_publish"] is True


def test_published_general_fee_follows_new_placement_and_scholarship_is_bounded(
    billing_workspace,
) -> None:
    engine, _user_id, ids, client = billing_workspace
    plan_id = create_plan(
        client,
        ids,
        name="Primary Seven general fee",
        class_id=ids["primary"],
        total=100_000,
    )
    duplicate = client.post(
        "/api/v1/fee-plans",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "class_id": str(ids["primary"]),
            "name": "Duplicate general fee",
            "academic_year": 2027,
            "term": 1,
            "currency": "UGX",
            "target_type": "cohort",
            "items": [{"category_id": str(ids["category"]), "amount": 100_000}],
            "installments": [
                {
                    "name": "Full term",
                    "calculation_type": "fixed",
                    "amount": 100_000,
                    "due_date": "2027-02-01",
                    "sort_order": 1,
                }
            ],
        },
    )
    assert duplicate.status_code == 409
    assert "general fee" in duplicate.json()["detail"]

    query = f"school_id={ids['school']}&period_id={ids['period']}"
    preview = client.get(f"/api/v1/billing/preview?{query}").json()
    published = client.post(
        "/api/v1/billing/publish",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "preview_token": preview["preview_token"],
            "idempotency_key": "publish-primary-general-fee",
        },
    )
    assert published.status_code == 201, published.text

    placement = client.post(
        f"/api/v1/students/{ids['learners'][2]}/transfer",
        json={
            "period_id": str(ids["period"]),
            "class_id": str(ids["primary"]),
            "stream_id": str(ids["east"]),
            "academic_year": 2027,
            "term": 1,
        },
    )
    assert placement.status_code == 200, placement.text
    assert placement.json()["fee_assignment"]["status"] == "assigned"
    assert placement.json()["fee_assignment"]["amount"] == "100000.00"

    registration = client.post(
        "/api/v1/students",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "first_name": "New",
            "last_name": "Learner",
            "gender": "female",
            "class_id": str(ids["primary"]),
            "stream_id": str(ids["east"]),
            "academic_year": 2027,
            "term": 1,
            "boarding_status": "day",
            "nationality": "Ugandan",
            "guardians": [
                {
                    "first_name": "Primary",
                    "last_name": "Guardian",
                    "relationship": "guardian",
                    "phone": "+256700000001",
                    "is_primary": True,
                }
            ],
        },
    )
    assert registration.status_code == 201, registration.text
    student_id = uuid.UUID(registration.json()["id"])

    with Session(engine) as session:
        assignment = session.scalar(
            select(StudentFeeAssignment).where(
                StudentFeeAssignment.student_id == student_id,
                StudentFeeAssignment.fee_structure_id == uuid.UUID(plan_id),
            )
        )
        assert assignment is not None
        assert assignment.amount == Decimal("100000.00")
        entries = session.scalars(
            select(LedgerEntry).where(LedgerEntry.student_id == student_id)
        ).all()
        assert len(entries) == 1
        assert entries[0].entry_type == "fee_charge"
        assert entries[0].amount == Decimal("100000.00")

    secondary_plan_id = create_plan(
        client,
        ids,
        name="Senior Four general fee",
        class_id=ids["secondary"],
        total=80_000,
    )
    with Session(engine) as session:
        secondary_plan = session.get(FeeStructure, uuid.UUID(secondary_plan_id))
        assert secondary_plan is not None
        secondary_plan.status = "published"
        session.commit()
    movement = client.post(
        f"/api/v1/students/{student_id}/transfer",
        json={
            "period_id": str(ids["period"]),
            "class_id": str(ids["secondary"]),
            "academic_year": 2027,
            "term": 1,
        },
    )
    assert movement.status_code == 200, movement.text
    assert movement.json()["fee_assignment"]["status"] == "review_required"
    movement_preview = client.get(f"/api/v1/billing/preview?{query}").json()
    moved_exclusion = next(
        item for item in movement_preview["exclusions"] if item["student_id"] == str(student_id)
    )
    assert "movement" in moved_exclusion["reason"]
    with Session(engine) as session:
        assignment_count = session.scalar(
            select(func.count(StudentFeeAssignment.id)).where(
                StudentFeeAssignment.student_id == student_id
            )
        )
        assert assignment_count == 1

    scholarship = client.post(
        "/api/v1/billing/adjustments",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "student_id": str(student_id),
            "category_id": str(ids["category"]),
            "adjustment_type": "sponsorship_credit",
            "amount": 25_000,
            "description": "Merit scholarship",
            "reason": "Approved by scholarship committee reference SC-100",
        },
    )
    assert scholarship.status_code == 201, scholarship.text
    over_credit = client.post(
        "/api/v1/billing/adjustments",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "student_id": str(student_id),
            "adjustment_type": "sponsorship_credit",
            "amount": 80_000,
            "description": "Second scholarship",
            "reason": "Should not exceed the remaining account balance",
        },
    )
    assert over_credit.status_code == 422
    assert "75000.00 UGX" in over_credit.json()["detail"]

    scholarship_preview = client.get(f"/api/v1/billing/preview?{query}").json()
    assert scholarship_preview["summary"]["credit_total"] == "25000.00"
    scholarship_post = client.post(
        "/api/v1/billing/publish",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "preview_token": scholarship_preview["preview_token"],
            "idempotency_key": "publish-new-learner-scholarship",
        },
    )
    assert scholarship_post.status_code == 201, scholarship_post.text
    with Session(engine) as session:
        balance = session.scalar(
            select(func.sum(LedgerEntry.amount)).where(LedgerEntry.student_id == student_id)
        )
        assert balance == Decimal("75000.00")


def test_unpublished_requirement_can_be_removed(billing_workspace) -> None:
    _engine, _user_id, ids, client = billing_workspace
    created = client.post(
        "/api/v1/requirements",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "name": "Draft candidate document",
            "code": "DRAFT-DOC",
            "requirement_type": "document",
            "academic_year": 2027,
            "term": 1,
            "amount": 0,
            "quantity": 1,
            "unit": "copy",
            "is_mandatory": True,
            "class_ids": [str(ids["secondary"])],
        },
    )
    assert created.status_code == 201, created.text
    removed = client.delete(f"/api/v1/requirements/{created.json()['id']}")
    assert removed.status_code == 204, removed.text
    query = f"school_id={ids['school']}&period_id={ids['period']}"
    assert client.get(f"/api/v1/requirements?{query}").json() == []


def test_auditor_cannot_publish_or_create_adjustments(billing_workspace) -> None:
    engine, user_id, ids, client = billing_workspace
    with Session(engine) as session:
        membership = session.scalar(
            select(SchoolMembership).where(SchoolMembership.auth_user_id == user_id)
        )
        assert membership is not None
        membership.role = "auditor"
        session.commit()
    adjustment = client.post(
        "/api/v1/billing/adjustments",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "student_id": str(ids["learners"][0]),
            "adjustment_type": "waiver",
            "amount": 10_000,
            "description": "Fee waiver",
            "reason": "Approved hardship support",
        },
    )
    assert adjustment.status_code == 403
    publish = client.post(
        "/api/v1/billing/publish",
        json={
            "school_id": str(ids["school"]),
            "period_id": str(ids["period"]),
            "preview_token": "a" * 64,
            "idempotency_key": "auditor-publish",
        },
    )
    assert publish.status_code == 403
