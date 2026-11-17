"""Verify production-relevant properties of the configured database connection."""

from sqlalchemy import text

from harambeeone_api.config import get_settings
from harambeeone_api.database import database_is_ready, get_engine


def main() -> None:
    settings = get_settings()
    if settings.app_environment != "production":
        raise RuntimeError("Production verification requires NODE_ENV=production")
    if not database_is_ready():
        raise RuntimeError("Database connection is not writable")

    with get_engine().connect() as connection:
        runtime = connection.execute(
            text(
                """
                select
                    coalesce(
                        (select ssl from pg_stat_ssl where pid = pg_backend_pid()),
                        false
                    ) as ssl,
                    (select setting::integer from pg_settings
                     where name = 'statement_timeout') as statement_timeout,
                    (select setting::integer from pg_settings
                     where name = 'lock_timeout') as lock_timeout,
                    (select setting::integer from pg_settings
                     where name = 'idle_in_transaction_session_timeout') as idle_timeout
                """
            )
        ).mappings().one()

    expected = {
        "statement_timeout": settings.database_statement_timeout_ms,
        "lock_timeout": settings.database_lock_timeout_ms,
        "idle_timeout": settings.database_idle_transaction_timeout_ms,
    }
    if runtime["ssl"] is not True:
        raise RuntimeError("Database transport is not encrypted")
    for setting, expected_value in expected.items():
        if runtime[setting] != expected_value:
            raise RuntimeError(
                f"Database {setting} is {runtime[setting]!r}; expected {expected_value!r}"
            )

    print("Database runtime verification passed")
    print(f"TLS: enabled ({settings.database_ssl_mode})")
    print(f"Statement timeout: {runtime['statement_timeout']}ms")
    print(f"Lock timeout: {runtime['lock_timeout']}ms")
    print(f"Idle transaction timeout: {runtime['idle_timeout']}ms")


if __name__ == "__main__":
    main()
