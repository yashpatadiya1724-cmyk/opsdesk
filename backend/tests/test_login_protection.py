import os
import sys
import time
import json
import socket
import subprocess
import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import User, Agency
from backend.app.auth import hash_password
from backend.app import main as main_module


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def clean_rate_limit_state():
    yield
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()


@pytest.fixture
def auth_user(db_session: Session):
    agency = db_session.query(Agency).filter(Agency.id == "AGY-TEST-LOGIN").first()
    if not agency:
        agency = Agency(id="AGY-TEST-LOGIN", name="Login Test Agency", country_code="US", tier="Standard")
        db_session.add(agency)
        db_session.flush()

    user = db_session.query(User).filter(User.email == "target_agent@travelcorp.com").first()
    if not user:
        user = User(
            id="USR-LOGIN-99",
            name="Target Agent",
            email="target_agent@travelcorp.com",
            role="Agent",
            region="US",
            agency_id=agency.id,
            hashed_password=hash_password("SuperSecurePassword123!")
        )
        db_session.add(user)
        db_session.commit()
    return user


def test_login_15_wrong_passwords_429_from_6th_testclient(client: TestClient, auth_user, caplog):
    """
    2.1 Login Protection:
    Per lower-cased email bucket: 5 failures / 15 minutes (900 seconds).
    15 wrong passwords -> 401 for 1..5, and 429 from the 6th onwards.
    """
    main_module._rate_limiter.reset(f"login_fail:email:{auth_user.email.lower()}")
    main_module._rate_limiter.reset("login_fail:ip:testclient")

    caplog.clear()

    responses = []
    for i in range(15):
        resp = client.post(
            "/api/auth/login",
            json={
                "email": "TARGET_AGENT@travelcorp.com ",  # test case and whitespace normalization
                "password": f"WrongPassword_{i}!"
            }
        )
        responses.append(resp)

    # 1st to 5th must be 401 Invalid credentials
    for i in range(5):
        assert responses[i].status_code == 401, f"Attempt {i+1} should be 401, got {responses[i].status_code}"
        assert responses[i].json() == {"detail": "Invalid credentials"}

    # 6th to 15th must be 429 Too Many Requests with Retry-After: 900
    for i in range(5, 15):
        assert responses[i].status_code == 429, f"Attempt {i+1} should be 429, got {responses[i].status_code}"
        assert responses[i].headers.get("Retry-After") == "900"
        assert "Rate limit exceeded" in responses[i].json()["detail"]

    # Verify structured logs did NOT contain the password
    for record in caplog.records:
        if "login_failed" in record.message:
            log_data = json.loads(record.message)
            assert log_data["event"] == "login_failed"
            assert log_data["email"] == auth_user.email.lower()
            assert "password" not in log_data
            for i in range(15):
                assert f"WrongPassword_{i}" not in record.message


def test_login_success_resets_email_failure_bucket(client: TestClient, auth_user):
    """
    2.1 Success resets the email failure bucket (clear failed attempts on successful login).
    """
    email_key = f"login_fail:email:{auth_user.email.lower()}"
    main_module._rate_limiter.reset(email_key)
    main_module._rate_limiter.reset("login_fail:ip:testclient")

    # 4 wrong password attempts
    for _ in range(4):
        resp = client.post(
            "/api/auth/login",
            json={"email": auth_user.email, "password": "BadPassword!"}
        )
        assert resp.status_code == 401

    # 5th attempt: correct password -> 200 OK and bucket cleared
    resp_success = client.post(
        "/api/auth/login",
        json={"email": auth_user.email, "password": "SuperSecurePassword123!"}
    )
    assert resp_success.status_code == 200
    data = resp_success.json()
    assert "access_token" in data

    # User now has a fresh bucket with 5 attempts allowed again
    for _ in range(4):
        resp = client.post(
            "/api/auth/login",
            json={"email": auth_user.email, "password": "BadPasswordAgain!"}
        )
        assert resp.status_code == 401, "Expected 401 because bucket was reset on success"


def test_login_identical_response_for_unknown_email_and_wrong_password(client: TestClient, auth_user):
    """
    2.1 Maintain identical 'Invalid credentials' response (HTTP 401, detail: 'Invalid credentials')
    for both unknown email and wrong password to prevent user enumeration.
    """
    main_module._rate_limiter.reset(f"login_fail:email:{auth_user.email.lower()}")
    main_module._rate_limiter.reset("login_fail:email:unknown_user_999@travelcorp.com")
    main_module._rate_limiter.reset("login_fail:ip:testclient")

    # Wrong password for existing user
    resp_wrong_pw = client.post(
        "/api/auth/login",
        json={"email": auth_user.email, "password": "IncorrectPassword!"}
    )
    # Unknown user
    resp_unknown_user = client.post(
        "/api/auth/login",
        json={"email": "unknown_user_999@travelcorp.com", "password": "AnyPassword!"}
    )

    assert resp_wrong_pw.status_code == 401
    assert resp_unknown_user.status_code == 401
    assert resp_wrong_pw.json() == resp_unknown_user.json() == {"detail": "Invalid credentials"}


def test_login_ip_failure_bucket_triggers_at_20_failures(client: TestClient, db_session: Session):
    """
    2.1 Per client IP bucket: 20 failures / 15 minutes (900 seconds).
    Even if attacker rotates across 25 different emails, IP bucket blocks from the 21st attempt.
    """
    main_module._rate_limiter.reset("login_fail:ip:testclient")

    responses = []
    for i in range(25):
        resp = client.post(
            "/api/auth/login",
            json={"email": f"attacker_target_{i}@example.com", "password": "WrongPassword!"}
        )
        responses.append(resp)

    # 1..20 should be 401
    for i in range(20):
        assert responses[i].status_code == 401, f"Attempt {i+1} should be 401"

    # 21..25 should be 429
    for i in range(20, 25):
        assert responses[i].status_code == 429, f"Attempt {i+1} should be 429"
        assert responses[i].headers.get("Retry-After") == "900"


@pytest.mark.slow
def test_login_real_uvicorn_server_15_wrong_passwords_subprocess(tmp_path):
    """
    2.1 Tests with a real uvicorn server in a subprocess:
    15 wrong passwords -> 429 from the 6th.
    """
    port = get_free_port()
    db_file = tmp_path / "uvicorn_login_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # Initialize schema on the temp db
    from sqlalchemy import create_engine
    from backend.app.database import ensure_schema_migrations
    temp_engine = create_engine(db_url)
    ensure_schema_migrations(temp_engine)
    temp_engine.dispose()

    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTHONPATH"] = "."
    env["DATABASE_URL"] = db_url
    env["AUTH_MODE"] = "jwt"
    env["JWT_SECRET"] = "a_very_secure_test_jwt_secret_key_at_least_32_chars!"
    env["RATE_LIMIT_BACKEND"] = "inmemory"
    env["SCORE_REFRESHER_ENABLED"] = "false"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning"
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    try:
        base_url = f"http://127.0.0.1:{port}"
        # Poll for readiness
        ready = False
        for _ in range(60):
            try:
                r = httpx.get(f"{base_url}/health", timeout=0.5)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.1)

        assert ready, "Uvicorn test server failed to start within 6 seconds"

        target_email = f"real_uvicorn_{int(time.time())}@travelcorp.com"
        responses = []

        with httpx.Client(base_url=base_url) as http_client:
            for i in range(15):
                resp = http_client.post(
                    "/api/auth/login",
                    json={"email": target_email, "password": f"Guess_{i}"}
                )
                responses.append(resp)

        # 1..5: 401
        for i in range(5):
            assert responses[i].status_code == 401, f"Real uvicorn attempt {i+1} got {responses[i].status_code}"
            assert responses[i].json() == {"detail": "Invalid credentials"}

        # 6..15: 429
        for i in range(5, 15):
            assert responses[i].status_code == 429, f"Real uvicorn attempt {i+1} got {responses[i].status_code}"
            assert responses[i].headers.get("Retry-After") == "900"
            assert "Rate limit exceeded" in responses[i].json()["detail"]

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
