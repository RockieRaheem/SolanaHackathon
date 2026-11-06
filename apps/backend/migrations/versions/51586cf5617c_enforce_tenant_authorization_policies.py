"""Enforce tenant authorization policies.

Revision ID: 51586cf5617c
Revises: 20261006_0900
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "51586cf5617c"
down_revision: str | None = "20261006_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_EXPRESSIONS = {
    "schools": "id",
    "school_programmes": "school_id",
    "academic_classes": "school_id",
    "streams": "(SELECT school_id FROM public.academic_classes WHERE id = streams.class_id)",
    "students": "school_id",
    "people": "private.person_school_id(id)",
    "enrollments": "(SELECT school_id FROM public.students WHERE id = enrollments.student_id)",
    "guardian_links": (
        "(SELECT school_id FROM public.students WHERE id = guardian_links.student_id)"
    ),
    "fee_structures": "school_id",
    "fee_categories": "school_id",
    "fee_structure_items": (
        "(SELECT school_id FROM public.fee_structures "
        "WHERE id = fee_structure_items.fee_structure_id)"
    ),
    "installment_rules": (
        "(SELECT school_id FROM public.fee_structures "
        "WHERE id = installment_rules.fee_structure_id)"
    ),
    "student_fee_assignments": (
        "(SELECT school_id FROM public.students WHERE id = student_fee_assignments.student_id)"
    ),
    "requirements": "school_id",
    "requirement_classes": (
        "(SELECT school_id FROM public.requirements WHERE id = requirement_classes.requirement_id)"
    ),
    "student_requirements": (
        "(SELECT school_id FROM public.requirements WHERE id = student_requirements.requirement_id)"
    ),
    "payments": "school_id",
    "payment_allocations": (
        "(SELECT school_id FROM public.payments WHERE id = payment_allocations.payment_id)"
    ),
    "ledger_entries": (
        "(SELECT school_id FROM public.students WHERE id = ledger_entries.student_id)"
    ),
    "stellar_anchors": (
        "(SELECT school_id FROM public.payments WHERE id = stellar_anchors.payment_id)"
    ),
    "statement_imports": "school_id",
    "statement_transactions": "school_id",
    "audit_events": "school_id",
    "sponsors": "private.sponsor_school_id(id)",
    "funding_programmes": "school_id",
    "programme_allocations": "school_id",
}

WRITE_ROLES = {
    "schools": ["owner"],
    "school_programmes": ["owner"],
    "academic_classes": ["owner"],
    "streams": ["owner"],
    "students": ["owner", "bursar"],
    "people": ["owner", "bursar"],
    "enrollments": ["owner", "bursar"],
    "guardian_links": ["owner", "bursar"],
    "fee_structures": ["owner", "bursar"],
    "fee_categories": ["owner", "bursar"],
    "fee_structure_items": ["owner", "bursar"],
    "installment_rules": ["owner", "bursar"],
    "student_fee_assignments": ["owner", "bursar"],
    "requirements": ["owner", "bursar"],
    "requirement_classes": ["owner", "bursar"],
    "student_requirements": ["owner", "bursar"],
    "payments": ["owner", "bursar", "cashier"],
    "payment_allocations": ["owner", "bursar", "cashier"],
    "ledger_entries": ["owner", "bursar", "cashier"],
    "stellar_anchors": ["owner", "bursar", "cashier"],
    "statement_imports": ["owner", "bursar"],
    "statement_transactions": ["owner", "bursar"],
    "audit_events": ["owner", "bursar", "cashier"],
    "sponsors": ["owner"],
    "funding_programmes": ["owner"],
    "programme_allocations": ["owner"],
}


def _role_array(roles: list[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{role}'" for role in roles) + "]::text[]"


def upgrade() -> None:
    op.execute("UPDATE school_memberships SET role = 'owner' WHERE role = 'owner_bursar'")
    op.create_check_constraint(
        "ck_school_memberships_role",
        "school_memberships",
        "role IN ('owner', 'bursar', 'cashier', 'auditor')",
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS private")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.has_school_role(
            target_school_id uuid,
            allowed_roles text[]
        ) RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT (SELECT auth.uid()) IS NOT NULL
               AND EXISTS (
                    SELECT 1
                    FROM public.school_memberships AS membership
                    WHERE membership.auth_user_id = (SELECT auth.uid())
                      AND membership.school_id = target_school_id
                      AND membership.role = ANY(allowed_roles)
               )
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.person_school_id(target_person_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT student.school_id FROM public.students AS student
            WHERE student.person_id = target_person_id
            UNION
            SELECT student.school_id
            FROM public.guardian_links AS guardian
            JOIN public.students AS student ON student.id = guardian.student_id
            WHERE guardian.person_id = target_person_id
            LIMIT 1
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION private.sponsor_school_id(target_sponsor_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT programme.school_id
            FROM public.funding_programmes AS programme
            WHERE programme.sponsor_id = target_sponsor_id
            LIMIT 1
        $$
        """
    )
    functions = (
        "has_school_role(uuid,text[])",
        "person_school_id(uuid)",
        "sponsor_school_id(uuid)",
    )
    for function in functions:
        op.execute(f"REVOKE ALL ON FUNCTION private.{function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION private.{function} TO authenticated")
    op.execute("REVOKE ALL ON SCHEMA private FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA private TO authenticated")

    op.execute(
        """
        CREATE POLICY school_memberships_select_own
        ON public.school_memberships FOR SELECT TO authenticated
        USING (auth_user_id = (SELECT auth.uid()))
        """
    )
    op.execute(
        """
        CREATE POLICY school_memberships_owner_manage
        ON public.school_memberships FOR ALL TO authenticated
        USING (private.has_school_role(school_id, ARRAY['owner']::text[]))
        WITH CHECK (private.has_school_role(school_id, ARRAY['owner']::text[]))
        """
    )

    read_roles = _role_array(["owner", "bursar", "cashier", "auditor"])
    for table, expression in TENANT_EXPRESSIONS.items():
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_select
            ON public."{table}" FOR SELECT TO authenticated
            USING (private.has_school_role({expression}, {read_roles}))
            """
        )
        write_roles = _role_array(WRITE_ROLES[table])
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write
            ON public."{table}" FOR ALL TO authenticated
            USING (private.has_school_role({expression}, {write_roles}))
            WITH CHECK (private.has_school_role({expression}, {write_roles}))
            """
        )


def downgrade() -> None:
    for table in reversed(TENANT_EXPRESSIONS):
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_write ON public."{table}"')
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_select ON public."{table}"')
    op.execute("DROP POLICY IF EXISTS school_memberships_owner_manage ON public.school_memberships")
    op.execute("DROP POLICY IF EXISTS school_memberships_select_own ON public.school_memberships")
    op.execute("DROP FUNCTION IF EXISTS private.sponsor_school_id(uuid)")
    op.execute("DROP FUNCTION IF EXISTS private.person_school_id(uuid)")
    op.execute("DROP FUNCTION IF EXISTS private.has_school_role(uuid,text[])")
    op.drop_constraint("ck_school_memberships_role", "school_memberships", type_="check")
    op.execute("UPDATE school_memberships SET role = 'owner_bursar' WHERE role = 'owner'")
