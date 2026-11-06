"""Verify portal role controls without retaining data."""

import hashlib
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from harambeeone_api import portals
from harambeeone_api.auth import AuthenticatedUser, SchoolContext
from harambeeone_api.config import get_settings
from harambeeone_api.models import (
    GuardianInvitation,
    GuardianLink,
    Person,
    School,
    Student,
)
from harambeeone_api.schemas import (
    DonorProfileCreate,
    GuardianInvitationAccept,
    GuardianInvitationCreate,
)

EXPECTED_HEAD = "e30afe762c9b"
TABLES = (
    "portal_profiles",
    "donor_profiles",
    "guardian_invitations",
    "guardian_account_links",
    "support_referrals",
)


def verify_live_workflow(connection) -> None:
    transaction = connection.begin()
    verification_name = f"Portal verification {uuid.uuid4().hex[:8]}"
    try:
        with Session(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            school = School(name=verification_name)
            learner_person = Person(first_name="Private", last_name="Learner")
            guardian_person = Person(
                first_name="Verified",
                last_name="Guardian",
                email=f"guardian-{uuid.uuid4().hex[:8]}@example.test",
            )
            session.add_all([school, learner_person, guardian_person])
            session.flush()
            learner = Student(
                school_id=school.id,
                person_id=learner_person.id,
                admission_no=f"PORTAL-{uuid.uuid4().hex[:8]}",
                gender="other",
            )
            session.add(learner)
            session.flush()
            guardian = GuardianLink(
                student_id=learner.id,
                person_id=guardian_person.id,
                relationship="guardian",
                is_primary=True,
            )
            session.add(guardian)
            session.commit()
            staff_context = SchoolContext(
                user=AuthenticatedUser(id=uuid.uuid4(), email="owner@example.test"),
                school_id=school.id,
                role="owner",
            )
            invitation = portals.create_guardian_invitation(
                GuardianInvitationCreate(
                    school_id=school.id,
                    guardian_link_id=guardian.id,
                ),
                session,
                staff_context,
            )
            raw_token = invitation["claim_token"]
            stored = session.scalar(
                select(GuardianInvitation).where(
                    GuardianInvitation.id == invitation["id"]
                )
            )
            assert stored is not None
            assert stored.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
            assert raw_token != stored.token_hash
            guardian_user = AuthenticatedUser(
                id=uuid.uuid4(), email=guardian_person.email
            )
            accepted = portals.accept_guardian_invitation(
                GuardianInvitationAccept(token=raw_token), guardian_user, session
            )
            assert accepted["linked"] is True
            learners = portals.list_guardian_learners(guardian_user, session)
            assert len(learners) == 1
            assert learners[0]["student_id"] == learner.id
            donor_user = AuthenticatedUser(
                id=uuid.uuid4(), email="donor@example.test"
            )
            portals.activate_donor_profile(
                DonorProfileCreate(
                    display_name="Verification donor", show_public_name=False
                ),
                donor_user,
                session,
            )
            donor_context = portals.get_my_portals(donor_user, session)
            assert [item["type"] for item in donor_context["portals"]] == ["donor"]
    finally:
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
            assert policy_count == 2, f"Expected two scoped policies on {table}"
            public_grants = connection.execute(
                text(
                    "select count(*) from information_schema.role_table_grants "
                    "where table_schema='public' and table_name=:table "
                    "and grantee in ('anon','authenticated')"
                ),
                {"table": table},
            ).scalar_one()
            assert public_grants == 0, f"Unexpected Data API grants on {table}"
        audit_triggers = connection.execute(
            text(
                "select count(*) from pg_trigger where not tgisinternal and tgname in "
                "('audit_guardian_invitations_insert','audit_guardian_invitations_update',"
                "'audit_guardian_account_links_insert','audit_guardian_account_links_update')"
            )
        ).scalar_one()
        referral_triggers = connection.execute(
            text(
                "select count(*) from pg_trigger where not tgisinternal and tgname in "
                "('audit_support_referrals_insert','audit_support_referrals_update')"
            )
        ).scalar_one()
        assert audit_triggers == 4
        assert referral_triggers == 2
        connection.rollback()
        verify_live_workflow(connection)
    engine.dispose()
    print(
        "Portal roles verified: migration head, owner-scoped RLS, revoked Data API grants, "
        "audit triggers, hashed one-time guardian invitation, linked-learner isolation, "
        "donor isolation, and full rollback passed"
    )


if __name__ == "__main__":
    main()
