"""add academic structure profiles

Revision ID: a07435e3724f
Revises: 20260916_1700
Create Date: 2026-09-29 09:59:06.703150
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a07435e3724f"
down_revision: str | None = "20260916_1700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "school_programmes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("programme_code", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("school_id", "programme_code"),
    )
    op.add_column("academic_classes", sa.Column("canonical_code", sa.String(32)))
    op.execute(
        """
        insert into school_programmes (id, school_id, programme_code, display_name, sort_order)
        select gen_random_uuid(), school_id, programme_code,
               case programme_code
                 when 'pre_primary' then 'Pre-primary / nursery'
                 when 'primary' then 'Primary'
                 when 'lower_secondary' then 'Lower secondary (O-Level)'
                 else 'Other'
               end,
               case programme_code
                 when 'pre_primary' then 2
                 when 'primary' then 3
                 when 'lower_secondary' then 4
                 else 9
               end
        from (
          select distinct school_id,
            case
              when level in ('baby', 'nursery', 'pre_primary') then 'pre_primary'
              when level = 'primary' then 'primary'
              when level in ('secondary', 'lower_secondary') then 'lower_secondary'
              else 'other'
            end as programme_code
          from academic_classes
        ) existing
        on conflict (school_id, programme_code) do nothing
        """
    )
    op.create_unique_constraint(
        "uq_academic_classes_school_canonical_code",
        "academic_classes",
        ["school_id", "canonical_code"],
    )
    op.execute(
        """
        update academic_classes
        set canonical_code = case upper(replace(name, '.', ''))
          when 'BABY CLASS' then 'BABY'
          when 'BABY' then 'BABY'
          when 'MIDDLE CLASS' then 'MIDDLE'
          when 'MIDDLE' then 'MIDDLE'
          when 'TOP CLASS' then 'TOP'
          when 'TOP' then 'TOP'
          when 'P1' then 'P1' when 'P2' then 'P2' when 'P3' then 'P3'
          when 'P4' then 'P4' when 'P5' then 'P5' when 'P6' then 'P6'
          when 'P7' then 'P7'
          when 'S1' then 'S1' when 'S2' then 'S2' when 'S3' then 'S3'
          when 'S4' then 'S4' when 'S5' then 'S5' when 'S6' then 'S6'
          else null
        end
        """
    )
    op.execute('alter table public."school_programmes" enable row level security')
    op.execute('revoke all on table public."school_programmes" from anon, authenticated')


def downgrade() -> None:
    op.drop_constraint(
        "uq_academic_classes_school_canonical_code",
        "academic_classes",
        type_="unique",
    )
    op.drop_column("academic_classes", "canonical_code")
    op.drop_table("school_programmes")
