from sqlalchemy import create_engine, text

from harambeeone_api.config import get_settings


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        membership_count = connection.scalar(text("SELECT count(*) FROM school_memberships"))
        rls_enabled = connection.scalar(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.school_memberships'::regclass"
            )
        )
        duplicate_users = connection.scalar(
            text(
                "SELECT count(*) FROM ("
                "SELECT auth_user_id FROM school_memberships "
                "GROUP BY auth_user_id HAVING count(*) > 1"
                ") duplicates"
            )
        )
    assert rls_enabled is True, "school_memberships must have RLS enabled"
    assert duplicate_users == 0, "A user must not be linked to multiple schools"
    print(f"Onboarding verified: memberships={membership_count}, rls=enabled, duplicates=0")


if __name__ == "__main__":
    main()
