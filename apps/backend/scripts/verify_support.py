"""Verify Harambee Support database controls without retaining data."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from harambeeone_api import support
from harambeeone_api.auth import AuthenticatedUser, SchoolContext
from harambeeone_api.config import get_settings
from harambeeone_api.models import (
    AcademicPeriod,
    AcademicYear,
    GuardianLink,
    LedgerEntry,
    Payment,
    Person,
    School,
    Student,
    SupportCase,
    SupportPaymentDestination,
    SupportPledge,
)
from harambeeone_api.schemas import (
    SupportAiReviewCreate,
    SupportAttestationCreate,
    SupportCaseCreate,
    SupportConsentCreate,
    SupportPledgeCreate,
    SupportPledgeVerify,
)

EXPECTED_HEAD = "7ac4d92e1b63"
TABLES = (
    "support_cases",
    "support_consents",
    "support_ai_reviews",
    "support_pledges",
    "support_attestations",
    "support_payment_destinations",
    "support_receipt_reissues",
)


def _gemma_review(**_kwargs) -> tuple[str, dict]:
    return (
        "gemma-4-26b-a4b-it",
        {
            "summary": "The anonymous school obligation is internally consistent.",
            "risk_level": "high",
            "observed_factors": ["A verified school balance remains outstanding"],
            "missing_information": [],
            "consistency_flags": [],
            "recommended_action": "A school owner should review the case for publication.",
            "safe_public_summary": (
                "A verified learner account needs support with an outstanding school obligation."
            ),
        },
    )


def verify_live_workflow(connection) -> None:
    """Exercise the complete service workflow in a rolled-back Supabase transaction."""
    transaction = connection.begin()
    original_gemma = support._call_gemma
    verification_name = f"Support verification {uuid.uuid4().hex[:8]}"
    try:
        support._call_gemma = _gemma_review
        with Session(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            school = School(name=verification_name)
            session.add(school)
            session.flush()
            year = AcademicYear(
                school_id=school.id,
                name="2098 Verification Year",
                year=2098,
                start_date=date(2098, 1, 1),
                end_date=date(2098, 12, 31),
                status="open",
            )
            session.add(year)
            session.flush()
            period = AcademicPeriod(
                academic_year_id=year.id,
                school_id=school.id,
                name="Verification term",
                sequence=1,
                opening_date=date(2098, 1, 1),
                due_date=date(2098, 2, 1),
                closing_date=date(2098, 4, 30),
                status="open",
            )
            learner_person = Person(first_name="Xylophonium", last_name="Obscurata")
            guardian_person = Person(first_name="Quasar", last_name="Custodian")
            session.add_all([period, learner_person, guardian_person])
            session.flush()
            student = Student(
                school_id=school.id,
                person_id=learner_person.id,
                admission_no=f"VERIFY-{uuid.uuid4().hex[:8]}",
                gender="other",
            )
            session.add(student)
            session.flush()
            guardian = GuardianLink(
                student_id=student.id,
                person_id=guardian_person.id,
                relationship="guardian",
                is_primary=True,
            )
            session.add_all(
                [
                    guardian,
                    LedgerEntry(
                        school_id=school.id,
                        period_id=period.id,
                        student_id=student.id,
                        entry_type="fee_charge",
                        amount=Decimal("500000"),
                        reference=f"VERIFY-BILL-{uuid.uuid4().hex[:8]}",
                        description="Support workflow verification charge",
                    ),
                ]
            )
            destination = SupportPaymentDestination(
                school_id=school.id,
                channel="bank",
                label="Verification bank account",
                provider_name="Verification Bank",
                account_name=school.name,
                account_reference=f"VERIFY-{uuid.uuid4().hex[:8]}",
                instructions="Pay the institution account and retain the settlement reference.",
                verification_status="verified",
                created_by="verification@harambeeone.local",
                verified_by="verification@harambeeone.local",
                verified_at=datetime.now(UTC),
            )
            session.add(destination)
            session.commit()
            context = SchoolContext(
                user=AuthenticatedUser(id=uuid.uuid4(), email="verification@harambeeone.local"),
                school_id=school.id,
                role="owner",
            )
            created = support.create_support_case(
                SupportCaseCreate(
                    school_id=school.id,
                    period_id=period.id,
                    student_id=student.id,
                    title="Keep an anonymous learner in class",
                    public_summary=(
                        "An anonymous learner has a verified outstanding school obligation."
                    ),
                    need_category="fees",
                    target_amount=Decimal("300000"),
                ),
                session,
                context,
            )
            case_id = created["id"]
            support.record_support_consent(
                case_id,
                SupportConsentCreate(
                    guardian_link_id=guardian.id,
                    method="signed_form",
                    anonymous_publication=True,
                    gemma_processing=True,
                    cross_border_processing=True,
                    child_assent_status="agreed",
                ),
                session,
                context,
            )
            support.review_support_case(
                case_id,
                SupportAiReviewCreate(),
                session,
                context,
            )
            published = support.publish_support_case(case_id, session, context)
            public_before = support.get_public_campaign(published["public_code"], session)
            assert "Xylophonium" not in str(public_before)
            assert "Obscurata" not in str(public_before)
            pledge_result = support.create_public_pledge(
                published["public_code"],
                SupportPledgeCreate(
                    payment_destination_id=destination.id,
                    idempotency_key=f"VERIFY-{uuid.uuid4().hex}",
                    external_reference=f"VERIFY-{uuid.uuid4().hex}",
                    donor_display_name="Verification donor",
                    amount=Decimal("300000"),
                ),
                session,
            )
            pledge = session.scalar(
                select(SupportPledge).where(
                    SupportPledge.public_reference == pledge_result["public_reference"]
                )
            )
            assert pledge is not None
            settled = support.verify_support_pledge(
                pledge.id,
                SupportPledgeVerify(action="verify"),
                session,
                context,
            )
            support.create_support_attestation(
                case_id,
                SupportAttestationCreate(
                    attestation_type="enrolment",
                    statement=(
                        "The supported learner remains enrolled in the current school period."
                    ),
                    attendance_band="90_plus",
                ),
                session,
                context,
            )
            tracked = support.track_public_pledge(
                published["public_code"], pledge.public_reference, session
            )
            public_after = support.get_public_campaign(published["public_code"], session)
            support_case = session.get(SupportCase, case_id)
            payment = session.scalar(select(Payment).where(Payment.id == pledge.payment_id))
            balance = session.scalar(
                select(LedgerEntry.amount)
                .where(
                    LedgerEntry.student_id == student.id,
                    LedgerEntry.payment_id == payment.id,
                )
                .limit(1)
            )
            assert settled["campaign_status"] == "funded"
            assert tracked["allocation"]["receipt_no"] == payment.receipt_no
            assert public_after["verified_amount"] == Decimal("300000")
            assert public_after["pending_amount"] == Decimal("0")
            assert public_after["attestations"][0]["attendance_band"] == "90_plus"
            assert support_case.status == "funded"
            assert balance == Decimal("-300000")
    finally:
        support._call_gemma = original_gemma
        transaction.rollback()
    remaining = connection.execute(
        select(School.id).where(School.name == verification_name)
    ).first()
    assert remaining is None, "Verification data was not rolled back"


def main() -> None:
    engine = create_engine(get_settings().migration_database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        head = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert head == EXPECTED_HEAD, f"Expected {EXPECTED_HEAD}, found {head}"
        for table in TABLES:
            rls = connection.execute(
                text(
                    "select relrowsecurity from pg_class c join pg_namespace n "
                    "on n.oid=c.relnamespace where n.nspname='public' and c.relname=:table"
                ),
                {"table": table},
            ).scalar_one()
            assert rls, f"RLS is disabled on {table}"
            policy_count = connection.execute(
                text(
                    "select count(*) from pg_policies "
                    "where schemaname='public' and tablename=:table"
                ),
                {"table": table},
            ).scalar_one()
            assert policy_count == 2, f"Expected two tenant policies on {table}"
            public_grants = connection.execute(
                text(
                    "select count(*) from information_schema.role_table_grants "
                    "where table_schema='public' and table_name=:table "
                    "and grantee in ('anon','authenticated')"
                ),
                {"table": table},
            ).scalar_one()
            assert public_grants == 0, f"Unexpected Data API grants on {table}"
        protection = connection.execute(
            text(
                "select count(*) from pg_trigger where not tgisinternal "
                "and tgname='protect_verified_support_pledges'"
            )
        ).scalar_one()
        assert protection == 1
        pledge_indexes = connection.execute(
            text(
                "select count(*) from pg_indexes where schemaname='public' "
                "and tablename='support_pledges' "
                "and indexname in ('ix_support_pledges_case_status', "
                "'support_pledges_public_reference_key')"
            )
        ).scalar_one()
        assert pledge_indexes == 2
        connection.rollback()
        verify_live_workflow(connection)
    engine.dispose()
    print(
        "Harambee Support verified: migration head, tenant RLS, revoked Data API grants, "
        "audit policies, immutable verified contributions, tracking indexes, and the "
        "rolled-back end-to-end financial workflow passed"
    )


if __name__ == "__main__":
    main()
