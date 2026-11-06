"""align payment workflow RLS with API permissions

Revision ID: d4e7a91c2f60
Revises: a72d5e8c19f4 (squashed DevFest compatibility path)
Create Date: 2026-10-26 06:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4e7a91c2f60"
down_revision: str | None = "a72d5e8c19f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DROP POLICY payment_receipt_sequences_owner_access "
        "ON public.payment_receipt_sequences"
    )
    op.execute(
        """
        CREATE POLICY payment_receipt_sequences_payment_writer
        ON public.payment_receipt_sequences FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar','cashier']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar','cashier']::text[]))
        """
    )

    op.execute("DROP POLICY payment_channels_owner_access ON public.payment_channels")
    op.execute(
        """
        CREATE POLICY payment_channels_staff_read
        ON public.payment_channels FOR SELECT TO authenticated
        USING (
            private.has_school_role(
                school_id, ARRAY['owner','bursar','cashier','auditor']::text[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY payment_channels_manager_write
        ON public.payment_channels FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner','bursar']::text[]))
        """
    )

    op.execute(
        "DROP POLICY payment_receipt_reissues_owner_access "
        "ON public.payment_receipt_reissues"
    )
    op.execute(
        """
        CREATE POLICY payment_receipt_reissues_staff_read
        ON public.payment_receipt_reissues FOR SELECT TO authenticated
        USING (
            private.has_school_role(
                school_id, ARRAY['owner','bursar','cashier','auditor']::text[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY payment_receipt_reissues_payment_writer
        ON public.payment_receipt_reissues FOR INSERT TO authenticated
        WITH CHECK (
            private.has_school_role(school_id, ARRAY['owner','bursar','cashier']::text[])
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY payment_receipt_reissues_payment_writer "
        "ON public.payment_receipt_reissues"
    )
    op.execute(
        "DROP POLICY payment_receipt_reissues_staff_read "
        "ON public.payment_receipt_reissues"
    )
    op.execute(
        """
        CREATE POLICY payment_receipt_reissues_owner_access
        ON public.payment_receipt_reissues FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )

    op.execute("DROP POLICY payment_channels_manager_write ON public.payment_channels")
    op.execute("DROP POLICY payment_channels_staff_read ON public.payment_channels")
    op.execute(
        """
        CREATE POLICY payment_channels_owner_access
        ON public.payment_channels FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )

    op.execute(
        "DROP POLICY payment_receipt_sequences_payment_writer "
        "ON public.payment_receipt_sequences"
    )
    op.execute(
        """
        CREATE POLICY payment_receipt_sequences_owner_access
        ON public.payment_receipt_sequences FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )
