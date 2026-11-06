"""normalize academic programme mappings

Revision ID: 076b76b8a490
Revises: a07435e3724f
Create Date: 2026-09-29 10:12:42.253913
"""

from collections.abc import Sequence

from alembic import op

revision: str = "076b76b8a490"
down_revision: str | None = "a07435e3724f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        update academic_classes
        set level = case
          when canonical_code in ('BABY', 'MIDDLE', 'TOP') then 'pre_primary'
          when canonical_code in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7') then 'primary'
          when canonical_code in ('S1', 'S2', 'S3', 'S4') then 'lower_secondary'
          when canonical_code in ('S5', 'S6') then 'upper_secondary'
          else level
        end
        """
    )
    op.execute(
        """
        insert into school_programmes (id, school_id, programme_code, display_name, sort_order)
        select gen_random_uuid(), school_id, 'upper_secondary',
               'Advanced secondary (A-Level)', 5
        from academic_classes
        where canonical_code in ('S5', 'S6')
        group by school_id
        on conflict (school_id, programme_code) do nothing
        """
    )


def downgrade() -> None:
    op.execute(
        """
        update academic_classes
        set level = case
          when level = 'pre_primary' then 'nursery'
          when level in ('lower_secondary', 'upper_secondary') then 'secondary'
          else level
        end
        """
    )
    op.execute("delete from school_programmes where programme_code = 'upper_secondary'")
