import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from backend.app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)
from backend.app.main import validate_production_auth_settings


def test_password_hashing_and_verification():
    """Verifies bcrypt password hashing and verification (with backward-compatibility)."""
    password = "demo123"
    hashed = hash_password(password)
    assert hashed.startswith("$2b$")
    assert verify_password("demo123", hashed) is True
    assert verify_password("wrongpassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(password, "") is False
    assert verify_password(password, "invalid$format") is False
    # Backward compatibility with legacy PBKDF2 hash
    legacy_hash = "pbkdf2_sha256$100000$00112233445566778899aabbccddeeff$80b618791fc58233b3276b0056d17689cdc51b726aff0f874c534698f4cd9dbc"
    assert verify_password("demo123", legacy_hash) is True


# 1. Successful login with correct email and demo123 returns valid token and 200
def test_login_successful(client: TestClient):
    """
    Case 1: Successful login with correct email and 'demo123'
    returns HTTP 200 with access_token, token_type='bearer', and expires_in.
    """
    payload = {
        "email": "aisha.ops@tbo.test",
        "password": "demo123"
    }
    resp = client.post("/api/auth/login", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 480 * 60

    # Verify token payload
    decoded = decode_access_token(data["access_token"])
    assert decoded["sub"] == "USR-101"
    assert decoded["email"] == "aisha.ops@tbo.test"
    assert decoded["role"] == "Agent"


# 2. Invalid password returns 401 Unauthorized
def test_login_invalid_credentials(client: TestClient):
    """
    Case 2: Invalid password or unknown email returns HTTP 401 Unauthorized
    with detail='Invalid credentials'.
    """
    # Invalid password
    resp = client.post("/api/auth/login", json={
        "email": "aisha.ops@tbo.test",
        "password": "wrongpassword"
    })
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"

    # Nonexistent user
    resp_unknown = client.post("/api/auth/login", json={
        "email": "unknown.user@tbo.test",
        "password": "demo123"
    })
    assert resp_unknown.status_code == 401
    assert resp_unknown.json()["detail"] == "Invalid credentials"


# 3. Valid token allows access to protected endpoints in AUTH_MODE=jwt
def test_jwt_mode_valid_token_allows_access(client: TestClient, monkeypatch):
    """
    Case 3: In AUTH_MODE=jwt, valid token passed via 'Authorization: Bearer <token>'
    allows access to protected endpoints (e.g. GET /api/tickets).
    """
    monkeypatch.setenv("AUTH_MODE", "jwt")

    login_resp = client.post("/api/auth/login", json={
        "email": "aisha.ops@tbo.test",
        "password": "demo123"
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    resp = client.get("/api/tickets", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data or "tickets" in data or isinstance(data, list)


# 4. Expired token returns 401 Unauthorized
def test_jwt_mode_expired_token_returns_401(client: TestClient, monkeypatch):
    """
    Case 4: In AUTH_MODE=jwt, an expired JWT token returns HTTP 401 Unauthorized.
    """
    monkeypatch.setenv("AUTH_MODE", "jwt")

    expired_token = create_access_token(
        data={"sub": "USR-101", "email": "aisha.ops@tbo.test"},
        expires_delta=timedelta(seconds=-60)
    )

    resp = client.get("/api/tickets", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


# 5. Tampered token returns 401 Unauthorized
def test_jwt_mode_tampered_token_returns_401(client: TestClient, monkeypatch):
    """
    Case 5: In AUTH_MODE=jwt, a tampered token (signature or payload modified)
    returns HTTP 401 Unauthorized.
    """
    monkeypatch.setenv("AUTH_MODE", "jwt")

    valid_token = create_access_token(data={"sub": "USR-101", "email": "aisha.ops@tbo.test"})
    parts = valid_token.split(".")

    # Tampered signature
    tampered_sig = ("X" if parts[2][0] != "X" else "Y") + parts[2][1:]
    tampered_sig_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    resp_sig = client.get("/api/tickets", headers={"Authorization": f"Bearer {tampered_sig_token}"})
    assert resp_sig.status_code == 401

    # Tampered payload
    tampered_payload = ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
    tampered_payload_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

    resp_payload = client.get("/api/tickets", headers={"Authorization": f"Bearer {tampered_payload_token}"})
    assert resp_payload.status_code == 401


# 6. Missing token in JWT mode returns 401 Unauthorized
def test_jwt_mode_missing_token_returns_401(client: TestClient, monkeypatch):
    """
    Case 6: In AUTH_MODE=jwt, requests missing the Authorization header
    (even with X-User-Id present) return HTTP 401 Unauthorized.
    """
    monkeypatch.setenv("AUTH_MODE", "jwt")

    # Missing Authorization header completely
    resp_none = client.get("/api/tickets")
    assert resp_none.status_code == 401
    assert "Missing Authorization" in resp_none.json()["detail"]

    # Only X-User-Id header provided
    resp_x_user = client.get("/api/tickets", headers={"X-User-Id": "USR-101"})
    assert resp_x_user.status_code == 401
    assert "Missing Authorization" in resp_x_user.json()["detail"]

    # Malformed Authorization header (not Bearer)
    resp_basic = client.get("/api/tickets", headers={"Authorization": "Basic 12345"})
    assert resp_basic.status_code == 401


# 7. Demo mode still works with X-User-Id
def test_demo_mode_works_with_x_user_id(client: TestClient, monkeypatch):
    """
    Case 7: In default AUTH_MODE=demo, requests authenticated via X-User-Id header
    succeed, and requests without credentials return 401.
    """
    monkeypatch.setenv("AUTH_MODE", "demo")

    resp = client.get("/api/tickets", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200

    # Missing X-User-Id returns 401 with expected detail
    resp_missing = client.get("/api/tickets")
    assert resp_missing.status_code == 401
    assert "Missing X-User-Id" in resp_missing.json()["detail"]

    # Unknown user returns 401 with expected detail
    resp_unknown = client.get("/api/tickets", headers={"X-User-Id": "USR-GHOST"})
    assert resp_unknown.status_code == 401
    assert "not found" in resp_unknown.json()["detail"]

    # Bearer token also accepted in demo mode if X-User-Id is omitted
    token = create_access_token(data={"sub": "USR-101"})
    resp_token = client.get("/api/tickets", headers={"Authorization": f"Bearer {token}"})
    assert resp_token.status_code == 200


# 8. Startup failure in production environment with demo mode when ALLOW_DEMO_AUTH is not true
def test_startup_failure_in_production_environment(monkeypatch):
    """
    Case 8: Startup failure in production environment with AUTH_MODE=demo
    when ALLOW_DEMO_AUTH is not true.
    """
    # 1. APP_ENV=production, AUTH_MODE=demo, ALLOW_DEMO_AUTH=false -> raises RuntimeError
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "false")

    with pytest.raises(RuntimeError) as exc_info:
        validate_production_auth_settings()
    assert "Production environment requires AUTH_MODE=jwt unless ALLOW_DEMO_AUTH=true" in str(exc_info.value)

    # 2. ENVIRONMENT=production (alternative env var) -> raises RuntimeError
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError) as exc_info2:
        validate_production_auth_settings()
    assert "Production environment requires AUTH_MODE=jwt unless ALLOW_DEMO_AUTH=true" in str(exc_info2.value)

    # 3. AUTH_MODE=jwt in production with valid secret -> allowed (does NOT raise)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET", "this_is_a_sufficiently_long_production_jwt_secret_32_chars")
    validate_production_auth_settings()

    # 4. ALLOW_DEMO_AUTH=true in production -> allowed (does NOT raise)
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "true")
    validate_production_auth_settings()


def test_jwt_mode_startup_refusal_empty_or_short_secret(monkeypatch):
    """
    Refuses startup in AUTH_MODE=jwt if JWT_SECRET is empty or shorter than 32 characters.
    """
    monkeypatch.setenv("AUTH_MODE", "jwt")

    # 1. Empty secret -> raises RuntimeError
    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(RuntimeError) as exc_info1:
        validate_production_auth_settings()
    assert "at least 32 characters long" in str(exc_info1.value)

    # 2. Secret shorter than 32 characters -> raises RuntimeError
    monkeypatch.setenv("JWT_SECRET", "too-short-secret-key-1234")
    with pytest.raises(RuntimeError) as exc_info2:
        validate_production_auth_settings()
    assert "at least 32 characters long" in str(exc_info2.value)

    # 3. Secret with whitespace padding that trims to < 32 chars -> raises RuntimeError
    monkeypatch.setenv("JWT_SECRET", "   short   ")
    with pytest.raises(RuntimeError) as exc_info3:
        validate_production_auth_settings()
    assert "at least 32 characters long" in str(exc_info3.value)

    # 4. Valid secret (>= 32 chars) -> succeeds without raising
    monkeypatch.setenv("JWT_SECRET", "this_is_a_valid_secret_key_with_at_least_32_chars!")
    validate_production_auth_settings()
