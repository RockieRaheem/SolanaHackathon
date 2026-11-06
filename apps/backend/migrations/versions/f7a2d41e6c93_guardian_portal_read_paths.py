"""add consented guardian portal read paths

Revision ID: f7a2d41e6c93
Revises: e5c8b20d4a71
Create Date: 2026-10-26 07:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a2d41e6c93"
down_revision: str | None = "e5c8b20d4a71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION private.guardian_has_school(target_school_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
          SELECT (SELECT auth.uid()) IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.guardian_account_links account
            WHERE account.auth_user_id = (SELECT auth.uid())
              AND account.school_id = target_school_id
          )
        $$;

        CREATE FUNCTION private.guardian_has_student(target_student_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
          SELECT (SELECT auth.uid()) IS NOT NULL AND EXISTS (
            SELECT 1
            FROM public.guardian_account_links account
            JOIN public.guardian_links guardian
              ON guardian.id = account.guardian_link_id
            WHERE account.auth_user_id = (SELECT auth.uid())
              AND guardian.student_id = target_student_id
          )
        $$;

        CREATE FUNCTION private.guardian_has_person(target_person_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
          SELECT (SELECT auth.uid()) IS NOT NULL AND EXISTS (
            SELECT 1
            FROM public.guardian_account_links account
            JOIN public.guardian_links guardian
              ON guardian.id = account.guardian_link_id
            JOIN public.students student ON student.id = guardian.student_id
            WHERE account.auth_user_id = (SELECT auth.uid())
              AND (student.person_id = target_person_id OR guardian.person_id = target_person_id)
          )
        $$;

        REVOKE ALL ON FUNCTION private.guardian_has_school(uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION private.guardian_has_student(uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION private.guardian_has_person(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION private.guardian_has_school(uuid) TO authenticated;
        GRANT EXECUTE ON FUNCTION private.guardian_has_student(uuid) TO authenticated;
        GRANT EXECUTE ON FUNCTION private.guardian_has_person(uuid) TO authenticated;

        CREATE POLICY schools_guardian_select ON public.schools
        FOR SELECT TO authenticated USING (private.guardian_has_school(id));
        CREATE POLICY students_guardian_select ON public.students
        FOR SELECT TO authenticated USING (private.guardian_has_student(id));
        CREATE POLICY people_guardian_select ON public.people
        FOR SELECT TO authenticated USING (private.guardian_has_person(id));
        CREATE POLICY guardian_links_guardian_select ON public.guardian_links
        FOR SELECT TO authenticated USING (private.guardian_has_student(student_id));
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY guardian_links_guardian_select ON public.guardian_links")
    op.execute("DROP POLICY people_guardian_select ON public.people")
    op.execute("DROP POLICY students_guardian_select ON public.students")
    op.execute("DROP POLICY schools_guardian_select ON public.schools")
    op.execute("DROP FUNCTION private.guardian_has_person(uuid)")
    op.execute("DROP FUNCTION private.guardian_has_student(uuid)")
    op.execute("DROP FUNCTION private.guardian_has_school(uuid)")
