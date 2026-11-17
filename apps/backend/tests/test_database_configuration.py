from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from harambeeone_api.config import Settings
from harambeeone_api.database import (
    create_database_engine,
    database_transport_connect_args,
    get_session,
)


def settings_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "NODE_ENV": "development",
        "database_url": "postgresql+psycopg://app:secret@db.example.test:5432/postgres",
        "migration_database_url": (
            "postgresql+psycopg://migrator:secret@db.example.test:5432/postgres"
        ),
        "supabase_url": "https://example.supabase.co",
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "publishable-test-key",
    }
    values.update(overrides)
    return values


def test_production_rejects_unverified_database_tls() -> None:
    with pytest.raises(ValidationError, match="DATABASE_SSL_MODE=verify-full"):
        Settings.model_validate(
            settings_values(
                NODE_ENV="production",
                database_ssl_mode="require",
                database_ssl_root_cert=__file__,
            )
        )


def test_production_rejects_missing_database_ca() -> None:
    with pytest.raises(ValidationError, match="DATABASE_SSL_ROOT_CERT"):
        Settings.model_validate(
            settings_values(NODE_ENV="production", database_ssl_mode="verify-full")
        )


def test_production_passes_verified_ca_to_database_driver() -> None:
    settings = Settings.model_validate(
        settings_values(
            NODE_ENV="production",
            database_ssl_mode="verify-full",
            database_ssl_root_cert=__file__,
        )
    )

    connect_args = database_transport_connect_args(
        settings, application_name="verification"
    )

    assert connect_args["sslmode"] == "verify-full"
    assert connect_args["sslrootcert"] == str(settings.database_ssl_root_cert)
    assert connect_args["application_name"] == "verification"


def test_engine_has_bounded_pool_and_database_timeouts(monkeypatch) -> None:
    settings = Settings.model_validate(settings_values())
    create_engine = Mock(return_value=Mock())
    monkeypatch.setattr("harambeeone_api.database.create_engine", create_engine)

    create_database_engine(settings)

    _, options = create_engine.call_args
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_timeout"] == 10
    assert options["pool_pre_ping"] is True
    assert options["pool_reset_on_return"] == "rollback"
    assert options["connect_args"]["sslmode"] == "require"
    assert "statement_timeout=15000" in options["connect_args"]["options"]
    assert "lock_timeout=5000" in options["connect_args"]["options"]
    assert "idle_in_transaction_session_timeout=30000" in options["connect_args"]["options"]


def test_session_rolls_back_and_closes_after_failure(monkeypatch) -> None:
    session = Mock()
    monkeypatch.setattr("harambeeone_api.database.Session", Mock(return_value=session))
    dependency = get_session()

    assert next(dependency) is session
    with pytest.raises(RuntimeError, match="failed operation"):
        dependency.throw(RuntimeError("failed operation"))

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
