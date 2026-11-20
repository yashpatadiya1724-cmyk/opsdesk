import logging
import pytest
from backend.app.main import validate_production_auth_settings


def test_production_auth_refusal_when_demo_auth_not_allowed(monkeypatch):
    """
    Lane B6: Verifies that running in APP_ENV=production refuses startup
    with a RuntimeError unless ALLOW_DEMO_AUTH=true.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "false")
    monkeypatch.setenv("BCRYPT_ROUNDS", "12")

    with pytest.raises(RuntimeError) as exc_info:
        validate_production_auth_settings()

    print(f"\n[RAW B6 RESULT Refusal] Exception: {exc_info.value}")
    assert "Refusing to start in APP_ENV=production" in str(exc_info.value)


def test_production_auth_allowed_with_explicit_override_and_warning(monkeypatch, caplog):
    """
    Lane B6: Verifies that APP_ENV=production allows startup if ALLOW_DEMO_AUTH=true,
    emitting a clear warning log.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "true")
    monkeypatch.setenv("BCRYPT_ROUNDS", "12")

    with caplog.at_level(logging.WARNING):
        validate_production_auth_settings()

    print("\n[RAW B6 RESULT Override Warnings]:", [r.message for r in caplog.records])
    assert any("ALLOW_DEMO_AUTH=true" in r.message for r in caplog.records)


def test_development_env_allows_demo_auth(monkeypatch):
    """
    Lane B6: Verifies that standard development environment starts without error.
    """
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "false")

    # Does not raise
    validate_production_auth_settings()
