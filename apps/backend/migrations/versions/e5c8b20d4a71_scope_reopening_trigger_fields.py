"""scope reopening trigger fields to ledger entries

Revision ID: e5c8b20d4a71
Revises: d4e7a91c2f60
Create Date: 2026-10-26 06:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c8b20d4a71"
down_revision: str | None = "d4e7a91c2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_function(*, scoped: bool) -> None:
    controlled_block = (
        """
          IF TG_TABLE_NAME = 'ledger_entries' AND TG_OP = 'INSERT' THEN
            IF NEW.reopening_correction_id IS NOT NULL THEN
              SELECT EXISTS (
                SELECT 1 FROM public.period_reopening_corrections correction
                WHERE correction.id = NEW.reopening_correction_id
                  AND correction.school_id = NEW.school_id
                  AND correction.student_id = NEW.student_id
                  AND target_period IN (correction.period_id, correction.destination_period_id)
              ) INTO controlled;
            END IF;
          END IF;
        """
        if scoped
        else """
          IF TG_TABLE_NAME = 'ledger_entries' AND TG_OP = 'INSERT'
             AND NEW.reopening_correction_id IS NOT NULL THEN
            SELECT EXISTS (
              SELECT 1 FROM public.period_reopening_corrections correction
              WHERE correction.id = NEW.reopening_correction_id
                AND correction.school_id = NEW.school_id
                AND correction.student_id = NEW.student_id
                AND target_period IN (correction.period_id, correction.destination_period_id)
            ) INTO controlled;
          END IF;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION private.reject_closed_period_mutation()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        DECLARE target_period uuid; controlled boolean := false;
        BEGIN
          target_period := CASE WHEN TG_OP = 'DELETE' THEN OLD.period_id ELSE NEW.period_id END;
          {controlled_block}
          IF NOT controlled AND EXISTS (
            SELECT 1 FROM public.academic_periods WHERE id = target_period AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'This academic period is closed and cannot be changed'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.period_id <> NEW.period_id AND EXISTS (
            SELECT 1 FROM public.academic_periods
            WHERE id = OLD.period_id AND status = 'closed'
          ) THEN
            RAISE EXCEPTION 'Records cannot be moved out of a closed academic period'
              USING ERRCODE = '23514';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        REVOKE ALL ON FUNCTION private.reject_closed_period_mutation() FROM PUBLIC;
        """
    )


def upgrade() -> None:
    _install_function(scoped=True)


def downgrade() -> None:
    _install_function(scoped=False)
