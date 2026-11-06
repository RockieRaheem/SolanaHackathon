import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from harambeeone_api.database import Base


class SchoolOrganization(Base):
    __tablename__ = "school_organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    emis_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    district: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    units: Mapped[list["School"]] = orm_relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class School(Base):
    __tablename__ = "schools"
    __table_args__ = (
        UniqueConstraint("organization_id", "unit_type", name="uq_schools_organization_unit_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("school_organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    unit_name: Mapped[str] = mapped_column(String(80), default="Main section")
    unit_type: Mapped[str] = mapped_column(String(32), default="custom")
    emis_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    district: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    organization: Mapped[SchoolOrganization | None] = orm_relationship(back_populates="units")

    @property
    def organization_name(self) -> str:
        return self.organization.name if self.organization else self.name

    classes: Mapped[list["AcademicClass"]] = orm_relationship(back_populates="school")
    programmes: Mapped[list["SchoolProgramme"]] = orm_relationship(
        back_populates="school",
        cascade="all, delete-orphan",
        order_by="SchoolProgramme.sort_order",
    )
    memberships: Mapped[list["SchoolMembership"]] = orm_relationship(
        back_populates="school", cascade="all, delete-orphan"
    )


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_years_school_name"),
        UniqueConstraint("school_id", "year", name="uq_academic_years_school_year"),
        CheckConstraint("start_date <= end_date", name="ck_academic_years_date_order"),
        CheckConstraint(
            "status in ('draft', 'open', 'closing', 'closed')",
            name="ck_academic_years_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    year: Mapped[int]
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    periods: Mapped[list["AcademicPeriod"]] = orm_relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        order_by="AcademicPeriod.sequence",
    )


class AcademicPeriod(Base):
    __tablename__ = "academic_periods"
    __table_args__ = (
        UniqueConstraint("academic_year_id", "sequence", name="uq_periods_year_sequence"),
        UniqueConstraint("academic_year_id", "name", name="uq_periods_year_name"),
        CheckConstraint("sequence > 0", name="ck_periods_positive_sequence"),
        CheckConstraint(
            "opening_date <= due_date and due_date <= closing_date",
            name="ck_periods_date_order",
        ),
        CheckConstraint(
            "status in ('draft', 'open', 'closing', 'closed')",
            name="ck_periods_status",
        ),
        Index(
            "uq_academic_periods_one_operational_per_school",
            "school_id",
            unique=True,
            postgresql_where=text("status in ('open', 'closing')"),
            sqlite_where=text("status in ('open', 'closing')"),
        ),
        Index("ix_academic_periods_school_dates", "school_id", "opening_date", "closing_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_years.id", ondelete="CASCADE"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int]
    opening_date: Mapped[date] = mapped_column(Date)
    closing_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    academic_year: Mapped[AcademicYear] = orm_relationship(back_populates="periods")


class SchoolMembership(Base):
    __tablename__ = "school_memberships"
    __table_args__ = (
        UniqueConstraint("school_id", "auth_user_id", name="uq_school_memberships_school_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    auth_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    member_email: Mapped[str | None] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(32), default="bursar")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    school: Mapped[School] = orm_relationship(back_populates="memberships")


class StaffInvitation(Base):
    __tablename__ = "staff_invitations"
    __table_args__ = (
        CheckConstraint("role in ('bursar','cashier','auditor')", name="ck_staff_invitations_role"),
        CheckConstraint(
            "status in ('pending','accepted','revoked','expired')",
            name="ck_staff_invitations_status",
        ),
        Index("ix_staff_invitations_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    invited_email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[uuid.UUID]
    created_by: Mapped[str] = mapped_column(String(254))
    accepted_by_user_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchoolProgramme(Base):
    __tablename__ = "school_programmes"
    __table_args__ = (UniqueConstraint("school_id", "programme_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    programme_code: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int]
    school: Mapped[School] = orm_relationship(back_populates="programmes")


class AcademicClass(Base):
    __tablename__ = "academic_classes"
    __table_args__ = (
        UniqueConstraint("school_id", "name"),
        UniqueConstraint(
            "school_id",
            "canonical_code",
            name="uq_academic_classes_school_canonical_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(20))
    canonical_code: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int]
    school: Mapped[School] = orm_relationship(back_populates="classes")
    streams: Mapped[list["Stream"]] = orm_relationship(
        back_populates="academic_class", cascade="all, delete-orphan"
    )


class Stream(Base):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("class_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(40))
    academic_class: Mapped[AcademicClass] = orm_relationship(back_populates="streams")


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(80))
    middle_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerIdentity(Base):
    __tablename__ = "learner_identities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school_organizations.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("school_id", "admission_no"),
        UniqueConstraint(
            "school_id",
            "learner_identification_number",
            name="uq_students_school_learner_identification",
        ),
        UniqueConstraint(
            "school_id", "learner_identity_id", name="uq_students_school_learner_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    learner_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="RESTRICT"), index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), unique=True)
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_identification_number: Mapped[str | None] = mapped_column(String(40))
    gender: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="active")
    boarding_status: Mapped[str] = mapped_column(String(20), default="day")
    nationality: Mapped[str] = mapped_column(String(60), default="Ugandan")
    previous_school: Mapped[str | None] = mapped_column(String(160))
    special_needs: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    person: Mapped[Person] = orm_relationship()
    enrollments: Mapped[list["Enrollment"]] = orm_relationship(back_populates="student")
    guardians: Mapped[list["GuardianLink"]] = orm_relationship(back_populates="student")
    fee_assignments: Mapped[list["StudentFeeAssignment"]] = orm_relationship()
    ledger_entries: Mapped[list["LedgerEntry"]] = orm_relationship()


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "academic_year", "term"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academic_classes.id"))
    stream_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("streams.id"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    academic_year: Mapped[int]
    term: Mapped[int]
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    student: Mapped[Student] = orm_relationship(back_populates="enrollments")
    academic_class: Mapped[AcademicClass] = orm_relationship()
    stream: Mapped[Stream | None] = orm_relationship()


class GuardianLink(Base):
    __tablename__ = "guardian_links"
    __table_args__ = (UniqueConstraint("student_id", "person_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"))
    relationship: Mapped[str] = mapped_column(String(30))
    is_primary: Mapped[bool] = mapped_column(default=False)
    can_receive_statements: Mapped[bool] = mapped_column(default=True)
    student: Mapped[Student] = orm_relationship(back_populates="guardians")
    person: Mapped[Person] = orm_relationship()


class LearnerTransferCase(Base):
    __tablename__ = "learner_transfer_cases"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','accepted','rejected','cancelled')",
            name="ck_learner_transfer_cases_status",
        ),
        CheckConstraint(
            "consent_method in ('written','digital','recorded_call','in_person')",
            name="ck_learner_transfer_cases_consent_method",
        ),
        Index("ix_learner_transfers_source_status", "source_school_id", "status"),
        Index("ix_learner_transfers_target_status", "target_school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    source_school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    target_school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    source_student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_links.id", ondelete="RESTRICT")
    )
    target_student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    purpose: Mapped[str] = mapped_column(String(240))
    consent_method: Mapped[str] = mapped_column(String(24))
    consent_reference: Mapped[str] = mapped_column(String(120))
    consent_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    learner_first_name: Mapped[str] = mapped_column(String(80))
    learner_middle_name: Mapped[str | None] = mapped_column(String(80))
    learner_last_name: Mapped[str] = mapped_column(String(80))
    learner_date_of_birth: Mapped[date | None] = mapped_column(Date)
    learner_gender: Mapped[str] = mapped_column(String(16))
    learner_identification_number: Mapped[str | None] = mapped_column(String(40))
    learner_boarding_status: Mapped[str] = mapped_column(String(20))
    learner_nationality: Mapped[str] = mapped_column(String(60))
    guardian_first_name: Mapped[str] = mapped_column(String(80))
    guardian_last_name: Mapped[str] = mapped_column(String(80))
    guardian_relationship: Mapped[str] = mapped_column(String(30))
    guardian_phone: Mapped[str | None] = mapped_column(String(32))
    guardian_email: Mapped[str | None] = mapped_column(String(254))
    created_by: Mapped[str] = mapped_column(String(254))
    decided_by: Mapped[str | None] = mapped_column(String(254))
    decision_reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationClient(Base):
    __tablename__ = "integration_clients"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_integration_clients_school_name"),
        CheckConstraint("status in ('active','revoked')", name="ck_integration_clients_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    key_prefix: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    scopes_json: Mapped[str] = mapped_column(Text)
    allowed_fields_json: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(240))
    lawful_basis: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="active")
    rate_limit_per_minute: Mapped[int] = mapped_column(default=60)
    request_window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationWebhookSubscription(Base):
    __tablename__ = "integration_webhook_subscriptions"
    __table_args__ = (
        UniqueConstraint("integration_client_id", "url", name="uq_integration_webhooks_url"),
        CheckConstraint("status in ('active','disabled')", name="ck_integration_webhooks_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    integration_client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="RESTRICT"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    signing_secret: Mapped[str] = mapped_column(String(96))
    event_types_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationOutboxEvent(Base):
    __tablename__ = "integration_outbox_events"
    __table_args__ = (Index("ix_integration_outbox_school_created", "school_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationDelivery(Base):
    __tablename__ = "integration_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "subscription_id", name="uq_integration_delivery_event_hook"),
        CheckConstraint(
            "status in ('pending','delivered','failed','abandoned')",
            name="ck_integration_deliveries_status",
        ),
        Index("ix_integration_deliveries_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_outbox_events.id", ondelete="RESTRICT"), index=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_webhook_subscriptions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0)
    last_response_code: Mapped[int | None]
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationExchangeLog(Base):
    __tablename__ = "integration_exchange_logs"
    __table_args__ = (
        CheckConstraint(
            "direction in ('export','import')", name="ck_integration_exchange_direction"
        ),
        Index("ix_integration_exchange_school_created", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    integration_client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="RESTRICT"), index=True
    )
    direction: Mapped[str] = mapped_column(String(12))
    resource_type: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(240))
    lawful_basis: Mapped[str] = mapped_column(String(120))
    fields_json: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    record_count: Mapped[int] = mapped_column(default=0)
    payload_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationImportBatch(Base):
    __tablename__ = "integration_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "integration_client_id", "idempotency_key", name="uq_integration_import_client_key"
        ),
        CheckConstraint(
            "status in ('validated','quarantined','acknowledged','rejected')",
            name="ck_integration_import_status",
        ),
        Index("ix_integration_import_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    integration_client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="RESTRICT"), index=True
    )
    resource_type: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    issues_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    record_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[str | None] = mapped_column(String(254))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortalProfile(Base):
    __tablename__ = "portal_profiles"
    __table_args__ = (
        CheckConstraint(
            "preferred_workspace is null or preferred_workspace in ('school','guardian','donor')",
            name="ck_portal_profiles_workspace",
        ),
    )

    auth_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    preferred_workspace: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GuardianInvitation(Base):
    __tablename__ = "guardian_invitations"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','accepted','revoked','expired')",
            name="ck_guardian_invitations_status",
        ),
        Index("ix_guardian_invitations_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_links.id", ondelete="RESTRICT"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_email: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(120))
    accepted_by_user_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuardianAccountLink(Base):
    __tablename__ = "guardian_account_links"
    __table_args__ = (
        UniqueConstraint("guardian_link_id", name="uq_guardian_account_links_guardian"),
        UniqueConstraint(
            "auth_user_id", "guardian_link_id", name="uq_guardian_account_links_user_guardian"
        ),
        Index("ix_guardian_account_links_user_school", "auth_user_id", "school_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_links.id", ondelete="RESTRICT"), index=True
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_invitations.id", ondelete="RESTRICT"), unique=True
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DonorProfile(Base):
    __tablename__ = "donor_profiles"

    auth_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    show_public_name: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SupportReferral(Base):
    __tablename__ = "support_referrals"
    __table_args__ = (
        UniqueConstraint("student_id", "period_id", name="uq_support_referrals_student_period"),
        CheckConstraint(
            "status in ('awaiting_consent','consented','declined','withdrawn','case_submitted')",
            name="ck_support_referrals_status",
        ),
        CheckConstraint(
            "child_assent_status in "
            "('pending','agreed','declined','not_applicable','unable_to_express')",
            name="ck_support_referrals_assent",
        ),
        Index("ix_support_referrals_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_links.id", ondelete="RESTRICT")
    )
    outstanding_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    overdue_since: Mapped[date] = mapped_column(Date)
    days_overdue_snapshot: Mapped[int]
    priority_band: Mapped[str] = mapped_column(String(16))
    priority_reasons: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_consent")
    privacy_notice_version: Mapped[str | None] = mapped_column(String(24))
    guardian_authority_confirmed: Mapped[bool] = mapped_column(default=False)
    age_verification_method: Mapped[str | None] = mapped_column(String(32))
    anonymous_publication: Mapped[bool] = mapped_column(default=False)
    gemma_processing: Mapped[bool] = mapped_column(default=False)
    cross_border_processing: Mapped[bool] = mapped_column(default=False)
    child_assent_status: Mapped[str] = mapped_column(String(24), default="pending")
    child_assent_reason: Mapped[str | None] = mapped_column(String(240))
    consented_by_user_id: Mapped[uuid.UUID | None]
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeeStructure(Base):
    __tablename__ = "fee_structures"
    __table_args__ = (
        CheckConstraint(
            "target_type in ('cohort', 'selected')", name="ck_fee_structures_target_type"
        ),
        CheckConstraint(
            "boarding_status is null or boarding_status in ('day', 'boarding', 'half_boarding')",
            name="ck_fee_structures_boarding_status",
        ),
        CheckConstraint("status in ('draft', 'published')", name="ck_fee_structures_status"),
        Index("ix_fee_structures_period_target", "period_id", "class_id", "stream_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academic_classes.id"))
    stream_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("streams.id"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    academic_year: Mapped[int]
    term: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    target_type: Mapped[str] = mapped_column(String(16), default="cohort")
    boarding_status: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list["FeeStructureItem"]] = orm_relationship(cascade="all, delete-orphan")
    installments: Mapped[list["InstallmentRule"]] = orm_relationship(cascade="all, delete-orphan")
    selected_learners: Mapped[list["FeeStructureLearner"]] = orm_relationship(
        cascade="all, delete-orphan"
    )


class FeeStructureLearner(Base):
    __tablename__ = "fee_structure_learners"
    __table_args__ = (UniqueConstraint("fee_structure_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fee_structure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fee_structures.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )


class FeeCategory(Base):
    __tablename__ = "fee_categories"
    __table_args__ = (UniqueConstraint("school_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(12))
    category_type: Mapped[str] = mapped_column(String(30), default="other")
    is_required: Mapped[bool] = mapped_column(default=True)
    is_recurring: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)


class FeeStructureItem(Base):
    __tablename__ = "fee_structure_items"
    __table_args__ = (UniqueConstraint("fee_structure_id", "category_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fee_structure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fee_structures.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fee_categories.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    category: Mapped[FeeCategory] = orm_relationship()


class InstallmentRule(Base):
    __tablename__ = "installment_rules"
    __table_args__ = (UniqueConstraint("fee_structure_id", "sort_order"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fee_structure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fee_structures.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    calculation_type: Mapped[str] = mapped_column(String(16), default="fixed")
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    due_date: Mapped[date]
    sort_order: Mapped[int]


class StudentFeeAssignment(Base):
    __tablename__ = "student_fee_assignments"
    __table_args__ = (UniqueConstraint("student_id", "fee_structure_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    fee_structure_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fee_structures.id"))
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_publications.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fee_structure: Mapped[FeeStructure] = orm_relationship()


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("school_id", "code", "academic_year", "term"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(20))
    requirement_type: Mapped[str] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(Text)
    academic_year: Mapped[int]
    term: Mapped[int]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(30), default="item")
    due_date: Mapped[date | None] = mapped_column(Date)
    stream_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("streams.id"))
    boarding_status: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    classes: Mapped[list["RequirementClass"]] = orm_relationship(
        cascade="all, delete-orphan", back_populates="requirement"
    )
    assignments: Mapped[list["StudentRequirement"]] = orm_relationship(
        cascade="all, delete-orphan", back_populates="requirement"
    )
    selected_learners: Mapped[list["RequirementLearner"]] = orm_relationship(
        cascade="all, delete-orphan"
    )


class RequirementClass(Base):
    __tablename__ = "requirement_classes"
    __table_args__ = (UniqueConstraint("requirement_id", "class_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT")
    )
    requirement: Mapped[Requirement] = orm_relationship(back_populates="classes")
    academic_class: Mapped[AcademicClass] = orm_relationship()


class RequirementLearner(Base):
    __tablename__ = "requirement_learners"
    __table_args__ = (UniqueConstraint("requirement_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )


class StudentRequirement(Base):
    __tablename__ = "student_requirements"
    __table_args__ = (UniqueConstraint("requirement_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_publications.id", ondelete="RESTRICT"), index=True
    )
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    fulfilled_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    is_waived: Mapped[bool] = mapped_column(default=False)
    waiver_reason: Mapped[str | None] = mapped_column(String(240))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilment_note: Mapped[str | None] = mapped_column(String(240))
    requirement: Mapped[Requirement] = orm_relationship(back_populates="assignments")
    student: Mapped[Student] = orm_relationship()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("school_id", "external_reference"),
        UniqueConstraint(
            "original_payment_id", "idempotency_key", name="uq_payment_correction_key"
        ),
        CheckConstraint(
            "transaction_type in ('receipt','reversal','refund')",
            name="ck_payments_transaction_type",
        ),
        CheckConstraint(
            "(transaction_type = 'receipt' and amount > 0) or "
            "(transaction_type in ('reversal','refund') and amount < 0)",
            name="ck_payments_amount_direction",
        ),
        Index("ix_payments_school_received", "school_id", "received_at"),
        Index("ix_payments_original", "original_payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True)
    external_reference: Mapped[str] = mapped_column(String(100))
    payer_name: Mapped[str | None] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(String(240))
    channel: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    status: Mapped[str] = mapped_column(String(24), default="reconciled")
    transaction_type: Mapped[str] = mapped_column(String(16), default="receipt")
    original_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT")
    )
    correction_reason: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[str | None] = mapped_column(String(120))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint(
            "allocation_type in ('fees','requirement','unallocated')",
            name="ck_payment_allocations_type",
        ),
        CheckConstraint("amount <> 0", name="ck_payment_allocations_amount"),
        Index("ix_payment_allocations_payment", "payment_id"),
        Index("ix_payment_allocations_student", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    requirement_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_requirements.id", ondelete="RESTRICT")
    )
    allocation_type: Mapped[str] = mapped_column(String(16), default="fees")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class PaymentReceiptSequence(Base):
    __tablename__ = "payment_receipt_sequences"
    __table_args__ = (
        CheckConstraint("next_number > 0", name="ck_payment_receipt_sequences_positive"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), primary_key=True
    )
    next_number: Mapped[int] = mapped_column(default=1)


class PaymentChannel(Base):
    __tablename__ = "payment_channels"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_payment_channels_school_code"),
        CheckConstraint(
            "channel_type in ('cash','bank','mobile_money','schoolpay','card','other')",
            name="ck_payment_channels_type",
        ),
        Index("ix_payment_channels_school_active", "school_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(80))
    channel_type: Mapped[str] = mapped_column(String(24))
    requires_reference: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentReceiptReissue(Base):
    __tablename__ = "payment_receipt_reissues"
    __table_args__ = (
        Index("ix_payment_receipt_reissues_payment_time", "payment_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str] = mapped_column(String(240))
    reissued_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingPublication(Base):
    __tablename__ = "billing_publications"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "period_id", "idempotency_key", name="uq_billing_publication_key"
        ),
        CheckConstraint("status in ('posted')", name="ck_billing_publications_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    preview_token: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="posted")
    learner_count: Mapped[int]
    charge_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingAdjustment(Base):
    __tablename__ = "billing_adjustments"
    __table_args__ = (
        CheckConstraint(
            "adjustment_type in ('addition', 'discount', 'sponsorship_credit', 'waiver')",
            name="ck_billing_adjustments_type",
        ),
        CheckConstraint("amount > 0", name="ck_billing_adjustments_amount"),
        CheckConstraint("status in ('draft', 'published')", name="ck_billing_adjustments_status"),
        Index("ix_billing_adjustments_period_student", "period_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fee_categories.id", ondelete="RESTRICT")
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_publications.id", ondelete="RESTRICT"), index=True
    )
    adjustment_type: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    description: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("fee_assignment_id"),
        UniqueConstraint("requirement_assignment_id"),
        UniqueConstraint("billing_adjustment_id"),
        Index("ix_ledger_entries_period_student", "period_id", "student_id"),
        Index("ix_ledger_entries_student_created", "student_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    entry_type: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    reference: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(240))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_publications.id", ondelete="RESTRICT"), index=True
    )
    fee_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_fee_assignments.id", ondelete="RESTRICT")
    )
    requirement_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_requirements.id", ondelete="RESTRICT")
    )
    billing_adjustment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_adjustments.id", ondelete="RESTRICT")
    )
    reopening_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("period_reopening_corrections.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArrearsFollowUp(Base):
    __tablename__ = "arrears_follow_ups"
    __table_args__ = (
        UniqueConstraint("school_id", "idempotency_key", name="uq_arrears_followup_key"),
        CheckConstraint(
            "contact_method in ('call','in_person','email','sms','whatsapp','letter','other')",
            name="ck_arrears_followups_method",
        ),
        CheckConstraint(
            "outcome in ('contacted','no_answer','commitment','dispute','statement_sent','other')",
            name="ck_arrears_followups_outcome",
        ),
        Index("ix_arrears_followups_account", "school_id", "period_id", "student_id", "created_at"),
        Index("ix_arrears_followups_next_action", "school_id", "next_action_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    contact_method: Mapped[str] = mapped_column(String(20))
    contacted_person: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(1000))
    next_action: Mapped[str | None] = mapped_column(String(240))
    next_action_date: Mapped[date | None] = mapped_column(Date)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArrearsPaymentPromise(Base):
    __tablename__ = "arrears_payment_promises"
    __table_args__ = (
        UniqueConstraint("follow_up_id", name="uq_arrears_promise_followup"),
        CheckConstraint("promised_amount > 0", name="ck_arrears_promises_amount"),
        CheckConstraint("paid_at_creation >= 0", name="ck_arrears_promises_paid_baseline"),
        CheckConstraint(
            "status in ('active','cancelled')", name="ck_arrears_promises_status"
        ),
        Index("ix_arrears_promises_account", "school_id", "period_id", "student_id", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    follow_up_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("arrears_follow_ups.id", ondelete="RESTRICT")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    promised_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_at_creation: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_by: Mapped[str | None] = mapped_column(String(120))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StellarAnchor(Base):
    __tablename__ = "stellar_anchors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), unique=True)
    commitment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    network: Mapped[str] = mapped_column(String(20), default="testnet")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    transaction_hash: Mapped[str | None] = mapped_column(String(64))
    ledger_number: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StatementImport(Base):
    __tablename__ = "statement_imports"
    __table_args__ = (
        UniqueConstraint("school_id", "content_hash", name="uq_statement_import_content"),
        UniqueConstraint("school_id", "idempotency_key", name="uq_statement_import_key"),
        CheckConstraint(
            "source_type in ('bank','mobile_money','schoolpay')",
            name="ck_statement_imports_source_type",
        ),
        Index("ix_statement_imports_school_period", "school_id", "period_id", "imported_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(160))
    source_type: Mapped[str] = mapped_column(String(24))
    content_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    row_count: Mapped[int]
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="review")
    imported_by: Mapped[str] = mapped_column(String(120))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StatementTransaction(Base):
    __tablename__ = "statement_transactions"
    __table_args__ = (
        UniqueConstraint("school_id", "source_reference"),
        CheckConstraint(
            "status in ('suggested','unmatched','reconciled','rejected','unidentified','reversed')",
            name="ck_statement_transactions_status",
        ),
        CheckConstraint(
            "channel in ('bank','mobile_money','schoolpay')",
            name="ck_statement_transactions_channel",
        ),
        Index(
            "ix_statement_transactions_school_period_status",
            "school_id",
            "period_id",
            "status",
            "transaction_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statement_imports.id", ondelete="CASCADE")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    transaction_date: Mapped[date]
    source_reference: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(240))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    channel: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default="unmatched")
    suggested_student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("students.id"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    match_reason: Mapped[str | None] = mapped_column(String(240))
    review_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), unique=True)
    payment_created_by_reconciliation: Mapped[bool] = mapped_column(default=False)
    reversal_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )


class CashierCollectionBatch(Base):
    __tablename__ = "cashier_collection_batches"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "period_id",
            "cashier_actor",
            "business_date",
            name="uq_cashier_batch_day",
        ),
        CheckConstraint(
            "status in ('open','submitted','returned','signed_off')",
            name="ck_cashier_batches_status",
        ),
        CheckConstraint("expected_cash >= 0", name="ck_cashier_batches_expected"),
        CheckConstraint("counted_cash >= 0", name="ck_cashier_batches_counted"),
        CheckConstraint("deposit_amount >= 0", name="ck_cashier_batches_deposit"),
        Index(
            "ix_cashier_batches_school_period_status",
            "school_id",
            "period_id",
            "status",
            "business_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    business_date: Mapped[date] = mapped_column(Date)
    cashier_actor: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="open")
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    counted_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    variance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deposit_reference: Mapped[str | None] = mapped_column(String(100))
    cashier_note: Mapped[str | None] = mapped_column(String(500))
    supervisor_note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_off_by: Mapped[str | None] = mapped_column(String(120))
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CashierBatchPayment(Base):
    __tablename__ = "cashier_batch_payments"
    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_cashier_batch_payment"),
        Index("ix_cashier_batch_payments_batch", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cashier_collection_batches.id", ondelete="RESTRICT")
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class PeriodClose(Base):
    __tablename__ = "period_closes"
    __table_args__ = (
        UniqueConstraint("period_id", name="uq_period_closes_period"),
        UniqueConstraint("school_id", "idempotency_key", name="uq_period_closes_key"),
        CheckConstraint("snapshot_version > 0", name="ck_period_closes_version"),
        CheckConstraint("learner_count >= 0", name="ck_period_closes_learner_count"),
        CheckConstraint("warning_count >= 0", name="ck_period_closes_warning_count"),
        Index("ix_period_closes_school_closed", "school_id", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    snapshot_version: Mapped[int] = mapped_column(default=1)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    learner_count: Mapped[int]
    warning_count: Mapped[int] = mapped_column(default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refunds: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reversals: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assessment_adjustments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_assessed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_collected: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    period_activity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    controls_json: Mapped[str] = mapped_column(Text)
    closed_by: Mapped[str] = mapped_column(String(120))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    learners: Mapped[list["PeriodCloseLearner"]] = orm_relationship(
        cascade="all, delete-orphan", order_by="PeriodCloseLearner.admission_no"
    )


class PeriodCloseLearner(Base):
    __tablename__ = "period_close_learners"
    __table_args__ = (
        UniqueConstraint("period_close_id", "student_id", name="uq_period_close_learner"),
        Index("ix_period_close_learners_school_student", "school_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    period_close_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT")
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT")
    )
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_name: Mapped[str] = mapped_column(String(240))
    class_name: Mapped[str] = mapped_column(String(40))
    stream_name: Mapped[str | None] = mapped_column(String(40))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refunds: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reversals: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assessment_adjustments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_assessed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_collected: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    period_activity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class BalanceCarryForward(Base):
    __tablename__ = "balance_carry_forwards"
    __table_args__ = (
        UniqueConstraint("source_close_id", name="uq_balance_carry_source_close"),
        UniqueConstraint("source_period_id", name="uq_balance_carry_source_period"),
        UniqueConstraint("destination_period_id", name="uq_balance_carry_destination_period"),
        UniqueConstraint("school_id", "idempotency_key", name="uq_balance_carry_key"),
        CheckConstraint("learner_count >= 0", name="ck_balance_carry_learner_count"),
        CheckConstraint("debt_total >= 0", name="ck_balance_carry_debt_total"),
        CheckConstraint("credit_total >= 0", name="ck_balance_carry_credit_total"),
        CheckConstraint(
            "source_period_id <> destination_period_id",
            name="ck_balance_carry_distinct_periods",
        ),
        CheckConstraint(
            "net_balance = debt_total - credit_total",
            name="ck_balance_carry_net_total",
        ),
        Index("ix_balance_carry_school_posted", "school_id", "posted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    source_close_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), index=True
    )
    source_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    destination_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    source_snapshot_hash: Mapped[str] = mapped_column(String(64))
    learner_count: Mapped[int]
    debt_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    posted_by: Mapped[str] = mapped_column(String(120))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["BalanceCarryForwardLine"]] = orm_relationship(
        cascade="all, delete-orphan", order_by="BalanceCarryForwardLine.admission_no"
    )


class BalanceCarryForwardLine(Base):
    __tablename__ = "balance_carry_forward_lines"
    __table_args__ = (
        UniqueConstraint("carry_forward_id", "student_id", name="uq_balance_carry_line_student"),
        UniqueConstraint(
            "destination_period_id",
            "student_id",
            name="uq_balance_carry_destination_student",
        ),
        UniqueConstraint("source_close_learner_id", name="uq_balance_carry_source_learner"),
        UniqueConstraint("ledger_entry_id", name="uq_balance_carry_ledger_entry"),
        CheckConstraint("amount <> 0", name="ck_balance_carry_line_nonzero"),
        Index(
            "ix_balance_carry_lines_school_student",
            "school_id",
            "student_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    carry_forward_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("balance_carry_forwards.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    source_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    destination_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    source_close_learner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_close_learners.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    ledger_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_entries.id", ondelete="RESTRICT"), index=True
    )
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_name: Mapped[str] = mapped_column(String(240))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class LearnerRollover(Base):
    __tablename__ = "learner_rollovers"
    __table_args__ = (
        UniqueConstraint("source_close_id", name="uq_learner_rollovers_source_close"),
        UniqueConstraint("source_period_id", name="uq_learner_rollovers_source_period"),
        UniqueConstraint(
            "destination_period_id", name="uq_learner_rollovers_destination_period"
        ),
        UniqueConstraint("school_id", "idempotency_key", name="uq_learner_rollovers_key"),
        CheckConstraint("candidate_count >= 0", name="ck_learner_rollovers_candidates"),
        CheckConstraint(
            "placed_count + held_count + completed_count + departed_count = candidate_count",
            name="ck_learner_rollovers_decision_totals",
        ),
        CheckConstraint(
            "source_period_id <> destination_period_id",
            name="ck_learner_rollovers_distinct_periods",
        ),
        Index("ix_learner_rollovers_school_applied", "school_id", "applied_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    source_close_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), index=True
    )
    source_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    destination_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    source_snapshot_hash: Mapped[str] = mapped_column(String(64))
    candidate_count: Mapped[int]
    placed_count: Mapped[int]
    held_count: Mapped[int]
    completed_count: Mapped[int]
    departed_count: Mapped[int]
    applied_by: Mapped[str] = mapped_column(String(120))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["LearnerRolloverLine"]] = orm_relationship(
        cascade="all, delete-orphan", order_by="LearnerRolloverLine.admission_no"
    )


class LearnerRolloverLine(Base):
    __tablename__ = "learner_rollover_lines"
    __table_args__ = (
        UniqueConstraint("rollover_id", "student_id", name="uq_rollover_lines_student"),
        UniqueConstraint("source_close_learner_id", name="uq_rollover_lines_source_learner"),
        UniqueConstraint("enrollment_id", name="uq_rollover_lines_enrollment"),
        CheckConstraint(
            "decision in ('continue','promote','repeat','hold','complete','depart')",
            name="ck_rollover_lines_decision",
        ),
        CheckConstraint(
            "(decision in ('continue','promote','repeat','hold') and new_status = 'active') "
            "or (decision = 'complete' and new_status = 'completed') "
            "or (decision = 'depart' and new_status = 'withdrawn')",
            name="ck_rollover_lines_result",
        ),
        Index("ix_rollover_lines_school_student", "school_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rollover_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_rollovers.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    source_close_learner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_close_learners.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("enrollments.id", ondelete="RESTRICT"), index=True
    )
    source_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT")
    )
    source_stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT")
    )
    target_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT")
    )
    target_stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT")
    )
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_name: Mapped[str] = mapped_column(String(240))
    source_class_name: Mapped[str] = mapped_column(String(80))
    source_stream_name: Mapped[str | None] = mapped_column(String(80))
    target_class_name: Mapped[str | None] = mapped_column(String(80))
    target_stream_name: Mapped[str | None] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(240))
    previous_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))


class PeriodReopening(Base):
    __tablename__ = "period_reopenings"
    __table_args__ = (
        UniqueConstraint("school_id", "idempotency_key", name="uq_period_reopenings_key"),
        UniqueConstraint("period_id", "snapshot_version", name="uq_period_reopenings_version"),
        CheckConstraint("snapshot_version > 1", name="ck_period_reopenings_version"),
        CheckConstraint("correction_count > 0", name="ck_period_reopenings_corrections"),
        CheckConstraint("learner_count >= 0", name="ck_period_reopenings_learners"),
        Index("ix_period_reopenings_school_period", "school_id", "period_id", "snapshot_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    original_close_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), index=True
    )
    previous_reopening_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("period_reopenings.id", ondelete="RESTRICT")
    )
    destination_period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(500))
    snapshot_version: Mapped[int]
    original_snapshot_hash: Mapped[str] = mapped_column(String(64))
    prior_snapshot_hash: Mapped[str] = mapped_column(String(64))
    revised_snapshot_hash: Mapped[str] = mapped_column(String(64))
    correction_count: Mapped[int]
    learner_count: Mapped[int]
    net_adjustment: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refunds: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reversals: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assessment_adjustments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_assessed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_collected: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    period_activity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    controls_json: Mapped[str] = mapped_column(Text)
    applied_by: Mapped[str] = mapped_column(String(120))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    corrections: Mapped[list["PeriodReopeningCorrection"]] = orm_relationship(
        cascade="all, delete-orphan", order_by="PeriodReopeningCorrection.admission_no"
    )
    learners: Mapped[list["PeriodReopeningLearner"]] = orm_relationship(
        cascade="all, delete-orphan", order_by="PeriodReopeningLearner.admission_no"
    )


class PeriodReopeningCorrection(Base):
    __tablename__ = "period_reopening_corrections"
    __table_args__ = (
        UniqueConstraint("reopening_id", "student_id", name="uq_reopening_correction_student"),
        CheckConstraint(
            "correction_type in ('charge','credit')", name="ck_reopening_correction_type"
        ),
        CheckConstraint("amount <> 0", name="ck_reopening_correction_amount"),
        CheckConstraint(
            "(correction_type = 'charge' and amount > 0) or "
            "(correction_type = 'credit' and amount < 0)",
            name="ck_reopening_correction_sign",
        ),
        Index("ix_reopening_corrections_school_student", "school_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reopening_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_reopenings.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    destination_period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    correction_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_name: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(String(240))
    reference: Mapped[str] = mapped_column(String(100), unique=True)


class PeriodReopeningLearner(Base):
    __tablename__ = "period_reopening_learners"
    __table_args__ = (
        UniqueConstraint("reopening_id", "student_id", name="uq_reopening_learner"),
        Index("ix_reopening_learners_school_student", "school_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reopening_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("period_reopenings.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT")
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT")
    )
    admission_no: Mapped[str] = mapped_column(String(40))
    learner_name: Mapped[str] = mapped_column(String(240))
    class_name: Mapped[str] = mapped_column(String(40))
    stream_name: Mapped[str | None] = mapped_column(String(40))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refunds: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reversals: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assessment_adjustments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_assessed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_collected: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    period_activity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    summary: Mapped[str] = mapped_column(String(240))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Sponsor(Base):
    __tablename__ = "sponsors"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    sponsor_type: Mapped[str] = mapped_column(String(30))
    country: Mapped[str] = mapped_column(String(80), default="Uganda")
    verification_status: Mapped[str] = mapped_column(String(20), default="verified")


class FundingProgramme(Base):
    __tablename__ = "funding_programmes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sponsor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sponsors.id"))
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProgrammeAllocation(Base):
    __tablename__ = "programme_allocations"
    __table_args__ = (UniqueConstraint("programme_id", "student_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    programme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funding_programmes.id"))
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"))
    beneficiary_ref: Mapped[str] = mapped_column(String(32), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    status: Mapped[str] = mapped_column(String(20), default="allocated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportCase(Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="ck_support_cases_target_amount"),
        CheckConstraint(
            "status in ('draft','changes_requested','submitted','review','approved',"
            "'published','funded','closed','withdrawn')",
            name="ck_support_cases_status",
        ),
        Index("ix_support_cases_school_status", "school_id", "status"),
        Index("ix_support_cases_student_period", "student_id", "period_id"),
        Index(
            "uq_support_cases_active_general_obligation",
            "student_id",
            "period_id",
            unique=True,
            postgresql_where=text(
                "requirement_assignment_id IS NULL AND status NOT IN ('closed','withdrawn')"
            ),
            sqlite_where=text(
                "requirement_assignment_id IS NULL AND status NOT IN ('closed','withdrawn')"
            ),
        ),
        Index(
            "uq_support_cases_active_requirement",
            "requirement_assignment_id",
            unique=True,
            postgresql_where=text(
                "requirement_assignment_id IS NOT NULL AND status NOT IN ('closed','withdrawn')"
            ),
            sqlite_where=text(
                "requirement_assignment_id IS NOT NULL AND status NOT IN ('closed','withdrawn')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    requirement_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_requirements.id", ondelete="RESTRICT"), index=True
    )
    referral_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("support_referrals.id", ondelete="RESTRICT"), unique=True, index=True
    )
    guardian_auth_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    public_code: Mapped[str] = mapped_column(String(24), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    public_summary: Mapped[str] = mapped_column(String(500))
    private_context: Mapped[str | None] = mapped_column(Text)
    need_category: Mapped[str] = mapped_column(String(40))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    risk_level: Mapped[str] = mapped_column(String(16), default="review")
    risk_reasons: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    review_notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportConsent(Base):
    __tablename__ = "support_consents"
    __table_args__ = (
        CheckConstraint("status in ('active','withdrawn')", name="ck_support_consents_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), unique=True, index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_links.id", ondelete="RESTRICT")
    )
    method: Mapped[str] = mapped_column(String(24))
    scope_version: Mapped[str] = mapped_column(String(24), default="2026-10")
    anonymous_publication: Mapped[bool] = mapped_column(default=True)
    gemma_processing: Mapped[bool] = mapped_column(default=False)
    cross_border_processing: Mapped[bool] = mapped_column(default=False)
    child_assent_status: Mapped[str] = mapped_column(String(24), default="not_applicable")
    status: Mapped[str] = mapped_column(String(16), default="active")
    recorded_by: Mapped[str] = mapped_column(String(120))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportAiReview(Base):
    __tablename__ = "support_ai_reviews"
    __table_args__ = (Index("ix_support_ai_reviews_case_time", "case_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    result_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportPledge(Base):
    __tablename__ = "support_pledges"
    __table_args__ = (
        UniqueConstraint("case_id", "external_reference"),
        CheckConstraint("amount > 0", name="ck_support_pledges_amount"),
        CheckConstraint(
            "status in ('pending','verified','rejected','reversed')",
            name="ck_support_pledges_status",
        ),
        Index("ix_support_pledges_case_status", "case_id", "status"),
        Index(
            "uq_support_pledges_case_idempotency",
            "case_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    payment_destination_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("support_payment_destinations.id", ondelete="RESTRICT"), index=True
    )
    donor_auth_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    public_reference: Mapped[str] = mapped_column(String(32), unique=True)
    external_reference: Mapped[str] = mapped_column(String(100))
    donor_display_name: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(120))
    rejection_reason: Mapped[str | None] = mapped_column(String(240))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[str | None] = mapped_column(String(120))
    reversal_reason: Mapped[str | None] = mapped_column(String(240))
    reversal_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )


class SupportPaymentDestination(Base):
    __tablename__ = "support_payment_destinations"
    __table_args__ = (
        UniqueConstraint("school_id", "channel", "account_reference"),
        CheckConstraint(
            "channel in ('schoolpay','bank','mobile_money')",
            name="ck_support_payment_destinations_channel",
        ),
        CheckConstraint(
            "verification_status in ('pending','verified','disabled')",
            name="ck_support_payment_destinations_status",
        ),
        Index("ix_support_payment_destinations_school_status", "school_id", "verification_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    channel: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(100))
    provider_name: Mapped[str] = mapped_column(String(100))
    account_name: Mapped[str] = mapped_column(String(160))
    account_reference: Mapped[str] = mapped_column(String(100))
    instructions: Mapped[str] = mapped_column(String(500))
    verification_status: Mapped[str] = mapped_column(String(16), default="pending")
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportReceiptSequence(Base):
    __tablename__ = "support_receipt_sequences"

    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), primary_key=True
    )
    next_number: Mapped[int] = mapped_column(default=1)


class SupportReceiptReissue(Base):
    __tablename__ = "support_receipt_reissues"
    __table_args__ = (Index("ix_support_receipt_reissues_pledge_time", "pledge_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    pledge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_pledges.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str] = mapped_column(String(240))
    reissued_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportAttestation(Base):
    __tablename__ = "support_attestations"
    __table_args__ = (
        CheckConstraint(
            "attestation_type in ('guardian_acknowledgement','fulfilment',"
            "'enrolment','independent_audit')",
            name="ck_support_attestations_type",
        ),
        CheckConstraint(
            "status in ('submitted','approved','rejected')",
            name="ck_support_attestations_status",
        ),
        Index("ix_support_attestations_case_time", "case_id", "verified_at"),
        Index("ix_support_attestations_school_status", "school_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT"), index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    attestation_type: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(String(500))
    redacted_statement: Mapped[str | None] = mapped_column(String(500))
    attendance_band: Mapped[str | None] = mapped_column(String(24))
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    is_public: Mapped[bool] = mapped_column(default=False)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    submitted_by_role: Mapped[str] = mapped_column(String(16), default="school")
    submitted_by: Mapped[str] = mapped_column(String(120))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(240))
    # Kept as compatibility aliases for receipts created before the S5 workflow.
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportNotification(Base):
    __tablename__ = "support_notifications"
    __table_args__ = (
        CheckConstraint(
            "recipient_type in ('school','guardian','donor')",
            name="ck_support_notifications_recipient_type",
        ),
        Index("ix_support_notifications_school_time", "school_id", "created_at"),
        Index("ix_support_notifications_user_time", "recipient_auth_user_id", "created_at"),
        Index("ix_support_notifications_email_time", "recipient_email", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    recipient_type: Mapped[str] = mapped_column(String(16))
    recipient_auth_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    recipient_email: Mapped[str | None] = mapped_column(String(254), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(500))
    href: Mapped[str] = mapped_column(String(300))
    related_type: Mapped[str] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID] = mapped_column()
    dedup_key: Mapped[str] = mapped_column(String(180), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportNotificationRead(Base):
    __tablename__ = "support_notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "auth_user_id"),
        Index("ix_support_notification_reads_user", "auth_user_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_notifications.id", ondelete="CASCADE"), index=True
    )
    auth_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportNotificationOutbox(Base):
    __tablename__ = "support_notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "status in ('ready','delivered','failed','cancelled')",
            name="ck_support_notification_outbox_status",
        ),
        Index("ix_support_notification_outbox_status_time", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_notifications.id", ondelete="CASCADE"), unique=True
    )
    channel: Mapped[str] = mapped_column(String(16), default="unassigned")
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="ready")
    attempt_count: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class SupportAssistantUsage(Base):
    __tablename__ = "support_assistant_usage"
    __table_args__ = (
        CheckConstraint(
            "persona in ('guardian','donor','school')",
            name="ck_support_assistant_usage_persona",
        ),
        CheckConstraint(
            "status in ('started','completed','failed','blocked')",
            name="ck_support_assistant_usage_status",
        ),
        Index(
            "ix_support_assistant_usage_user_time",
            "auth_user_id",
            "persona",
            "created_at",
        ),
        Index("ix_support_assistant_usage_school_time", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    auth_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    persona: Mapped[str] = mapped_column(String(16))
    task: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    model_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
