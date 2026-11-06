"""add controlled support contributions and receipts

Revision ID: 7ac4d92e1b63
Revises: f42c8e910ab7
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7ac4d92e1b63"
down_revision: str | None = "f42c8e910ab7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _secure_school_table(table: str, write_roles: str) -> None:
    op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute(
        f"CREATE POLICY {table}_tenant_read ON public.\"{table}\" FOR SELECT TO authenticated "
        "USING (private.has_school_role(school_id, "
        "ARRAY['owner','bursar','cashier','auditor']::text[]))"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_write ON public.\"{table}\" FOR ALL TO authenticated "
        f"USING (private.has_school_role(school_id, {write_roles})) "
        f"WITH CHECK (private.has_school_role(school_id, {write_roles}))"
    )
    op.execute(
        f'CREATE TRIGGER audit_{table}_insert AFTER INSERT ON public."{table}" '
        "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
    )
    op.execute(
        f'CREATE TRIGGER audit_{table}_update AFTER UPDATE ON public."{table}" '
        "FOR EACH ROW EXECUTE FUNCTION public.capture_audit_event()"
    )


def upgrade() -> None:
    op.create_table(
        "support_payment_destinations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("account_name", sa.String(160), nullable=False),
        sa.Column("account_reference", sa.String(100), nullable=False),
        sa.Column("instructions", sa.String(500), nullable=False),
        sa.Column(
            "verification_status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("verified_by", sa.String(120)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("school_id", "channel", "account_reference"),
        sa.CheckConstraint(
            "channel in ('schoolpay','bank','mobile_money')",
            name="ck_support_payment_destinations_channel",
        ),
        sa.CheckConstraint(
            "verification_status in ('pending','verified','disabled')",
            name="ck_support_payment_destinations_status",
        ),
    )
    op.create_index(
        "ix_support_payment_destinations_school_id",
        "support_payment_destinations",
        ["school_id"],
    )
    op.create_index(
        "ix_support_payment_destinations_school_status",
        "support_payment_destinations",
        ["school_id", "verification_status"],
    )
    op.create_table(
        "support_receipt_sequences",
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("next_number > 0", name="ck_support_receipt_sequences_positive"),
    )
    op.add_column(
        "support_pledges",
        sa.Column(
            "payment_destination_id",
            sa.Uuid(),
            sa.ForeignKey("support_payment_destinations.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column("support_pledges", sa.Column("donor_auth_user_id", sa.Uuid()))
    op.add_column("support_pledges", sa.Column("idempotency_key", sa.String(80)))
    op.add_column("support_pledges", sa.Column("rejection_reason", sa.String(240)))
    op.add_column("support_pledges", sa.Column("reversed_at", sa.DateTime(timezone=True)))
    op.add_column("support_pledges", sa.Column("reversed_by", sa.String(120)))
    op.add_column("support_pledges", sa.Column("reversal_reason", sa.String(240)))
    op.add_column(
        "support_pledges",
        sa.Column(
            "reversal_payment_id",
            sa.Uuid(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index(
        "ix_support_pledges_payment_destination_id",
        "support_pledges",
        ["payment_destination_id"],
    )
    op.create_index(
        "ix_support_pledges_donor_auth_user_id", "support_pledges", ["donor_auth_user_id"]
    )
    op.create_index(
        "uq_support_pledges_case_idempotency",
        "support_pledges",
        ["case_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_support_pledges_reversal_payment_id",
        "support_pledges",
        ["reversal_payment_id"],
        unique=True,
    )
    op.drop_constraint("ck_support_pledges_status", "support_pledges", type_="check")
    op.create_check_constraint(
        "ck_support_pledges_status",
        "support_pledges",
        "status in ('pending','verified','rejected','reversed')",
    )
    op.create_table(
        "support_receipt_reissues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pledge_id",
            sa.Uuid(),
            sa.ForeignKey("support_pledges.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("reissued_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_support_receipt_reissues_school_id", "support_receipt_reissues", ["school_id"]
    )
    op.create_index(
        "ix_support_receipt_reissues_pledge_id", "support_receipt_reissues", ["pledge_id"]
    )
    op.create_index(
        "ix_support_receipt_reissues_pledge_time",
        "support_receipt_reissues",
        ["pledge_id", "created_at"],
    )

    _secure_school_table(
        "support_payment_destinations", "ARRAY['owner']::text[]"
    )
    _secure_school_table(
        "support_receipt_reissues", "ARRAY['owner','bursar']::text[]"
    )
    op.execute("ALTER TABLE public.support_receipt_sequences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE ALL ON TABLE public.support_receipt_sequences FROM anon, authenticated"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.protect_verified_support_pledge()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.status IN ('verified', 'reversed') THEN
                RAISE EXCEPTION 'Posted support contributions are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'verified' THEN
                IF NEW.status = 'reversed'
                   AND NEW.reversal_payment_id IS NOT NULL
                   AND NEW.reversal_reason IS NOT NULL
                   AND NEW.case_id = OLD.case_id
                   AND NEW.school_id = OLD.school_id
                   AND NEW.amount = OLD.amount
                   AND NEW.payment_id = OLD.payment_id
                   AND NEW.external_reference = OLD.external_reference THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Verified support contributions are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'reversed' THEN
                RAISE EXCEPTION 'Reversed support contributions are immutable';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION private.protect_verified_support_pledge() "
        "FROM PUBLIC, anon, authenticated"
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.protect_verified_support_pledge()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
            IF OLD.status = 'verified' THEN
                RAISE EXCEPTION 'Verified support contributions are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in ("support_receipt_reissues", "support_payment_destinations"):
        op.execute(f'DROP TRIGGER audit_{table}_update ON public."{table}"')
        op.execute(f'DROP TRIGGER audit_{table}_insert ON public."{table}"')
    op.drop_table("support_receipt_reissues")
    op.drop_constraint("ck_support_pledges_status", "support_pledges", type_="check")
    op.create_check_constraint(
        "ck_support_pledges_status",
        "support_pledges",
        "status in ('pending','verified','rejected')",
    )
    op.drop_index("uq_support_pledges_reversal_payment_id", table_name="support_pledges")
    op.drop_index("uq_support_pledges_case_idempotency", table_name="support_pledges")
    op.drop_index("ix_support_pledges_donor_auth_user_id", table_name="support_pledges")
    op.drop_index("ix_support_pledges_payment_destination_id", table_name="support_pledges")
    for column in (
        "reversal_payment_id",
        "reversal_reason",
        "reversed_by",
        "reversed_at",
        "rejection_reason",
        "idempotency_key",
        "donor_auth_user_id",
        "payment_destination_id",
    ):
        op.drop_column("support_pledges", column)
    op.drop_table("support_receipt_sequences")
    op.drop_table("support_payment_destinations")
