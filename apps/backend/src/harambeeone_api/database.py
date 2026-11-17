from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

from harambeeone_api.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


# Import model modules so Alembic can discover their metadata.
from harambeeone_api import models  # noqa: E402, F401


@lru_cache
def get_engine() -> Engine:
    return create_database_engine(get_settings())


def database_transport_connect_args(
    settings: Settings, *, application_name: str
) -> dict[str, str | int]:
    connect_args: dict[str, str | int] = {
        "connect_timeout": settings.database_connect_timeout_seconds,
        "sslmode": settings.database_ssl_mode,
        "application_name": application_name,
    }
    if settings.database_ssl_root_cert is not None:
        connect_args["sslrootcert"] = str(settings.database_ssl_root_cert)
    return connect_args


def create_database_engine(settings: Settings) -> Engine:
    connect_args = database_transport_connect_args(
        settings, application_name="harambeeone-api"
    )
    connect_args["options"] = " ".join(
        (
            f"-c statement_timeout={settings.database_statement_timeout_ms}",
            f"-c lock_timeout={settings.database_lock_timeout_ms}",
            "-c idle_in_transaction_session_timeout="
            f"{settings.database_idle_transaction_timeout_ms}",
        )
    )

    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_use_lifo=True,
        pool_reset_on_return="rollback",
    )


def get_session() -> Iterator[Session]:
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def database_is_ready() -> bool:
    with get_engine().connect() as connection:
        return connection.execute(
            text("select current_setting('transaction_read_only') = 'off'")
        ).scalar_one() is True
