from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

from harambeeone_api.config import get_settings


class Base(DeclarativeBase):
    pass


# Import model modules so Alembic can discover their metadata.
from harambeeone_api import models  # noqa: E402, F401


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        connect_args={"connect_timeout": 5},
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        # Supabase is a remote database; pre-ping doubles the network round trips
        # for every request. Short recycling keeps pooled connections fresh without
        # putting an extra query on the critical path.
        pool_pre_ping=False,
        pool_recycle=120,
    )


def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def database_is_ready() -> bool:
    with get_engine().connect() as connection:
        return connection.execute(text("select 1")).scalar_one() == 1
