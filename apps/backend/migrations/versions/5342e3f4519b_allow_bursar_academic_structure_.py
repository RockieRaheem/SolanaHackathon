"""allow bursar academic structure management

Revision ID: 5342e3f4519b
Revises: 51586cf5617c
Create Date: 2026-10-09 00:21:08.361218
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5342e3f4519b"
down_revision: str | None = "51586cf5617c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("school_programmes", "academic_classes", "streams"):
        op.execute(f'DROP POLICY {table}_tenant_write ON public."{table}"')
        expression = {
            "school_programmes": "school_id",
            "academic_classes": "school_id",
            "streams": (
                "(SELECT school_id FROM public.academic_classes WHERE id = streams.class_id)"
            ),
        }[table]
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write
            ON public."{table}" FOR ALL TO authenticated
            USING (
                private.has_school_role(
                    {expression}, ARRAY['owner', 'bursar']::text[]
                )
            )
            WITH CHECK (
                private.has_school_role(
                    {expression}, ARRAY['owner', 'bursar']::text[]
                )
            )
            """
        )


def downgrade() -> None:
    for table in ("school_programmes", "academic_classes", "streams"):
        op.execute(f'DROP POLICY {table}_tenant_write ON public."{table}"')
        expression = {
            "school_programmes": "school_id",
            "academic_classes": "school_id",
            "streams": (
                "(SELECT school_id FROM public.academic_classes WHERE id = streams.class_id)"
            ),
        }[table]
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write
            ON public."{table}" FOR ALL TO authenticated
            USING (private.has_school_role({expression}, ARRAY['owner']::text[]))
            WITH CHECK (private.has_school_role({expression}, ARRAY['owner']::text[]))
            """
        )
