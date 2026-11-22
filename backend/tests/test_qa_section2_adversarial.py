"""
backend/tests/test_qa_section2_adversarial.py
Adversarial QA Test Suite for Section 2 (Round 10).
Tests edge cases in:
1. Email canonicalization in login failure rate limit bucket.
2. Pre-auth X-User-Id spoofing protection in protection middleware.
3. Streaming request body size limit enforcement without / spoofed Content-Length.
4. Strict security headers on 401, 404, 413, and 429 error responses for /api/*.
"""

import os
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app, _rate_limiter
from backend.app.auth import create_access_token


@pytest.fixture(autouse=True)
def reset_rate_limiter_buckets():
    """Ensure a clean rate limiter state before each adversarial test."""
    if hasattr(_rate_limiter, "_records"):
        with getattr(_rate_limiter, "_lock", None) or type("NoopLock", (), {"__enter__": lambda s: None, "__exit__": lambda s, *a: None})():
            _rate_limiter._records.clear()
    yield


# ============================================================================
# 1. EMAIL CANONICALIZATION IN LOGIN FAILURE BUCKET
# ============================================================================
def test_adversarial_login_failure_email_canonicalization(client: TestClient):
    """
    Edge Case 1: Case variations and surrounding whitespace must all count
    against the SAME failure bucket, preventing case-mutation evasion of the
    5-attempt brute-force limit.
    """
    target_email = "elena.rostova@opsdesk.internal"
    permutations = [
        "elena.rostova@opsdesk.internal",
        "ELENA.ROSTOVA@OPSDESK.INTERNAL",
        "  elena.rostova@opsdesk.internal  ",
        "Elena.Rostova@OpsDesk.Internal",
        "  ELENA.ROSTOVA@opsdesk.internal",
    ]

    # First 5 attempts fail with 401 Unauthorized
    for idx, email_variant in enumerate(permutations, start=1):
        resp = client.post("/api/auth/login", json={
            "email": email_variant,
            "password": f"wrong-pass-{idx}"
        })
        assert resp.status_code == 401, f"Attempt {idx} ({email_variant}) expected 401, got {resp.status_code}"
        assert resp.json()["detail"] == "Invalid credentials"

    # 6th attempt with another case permutation must be throttled with 429
    locked_variant = "eLeNa.RoStOvA@OPSDESK.INTERNAL  "
    resp_locked = client.post("/api/auth/login", json={
        "email": locked_variant,
        "password": "wrong-pass-6"
    })
    assert resp_locked.status_code == 429, f"6th attempt expected 429, got {resp_locked.status_code}"
    assert resp_locked.headers.get("Retry-After") == "900" or resp_locked.headers.get("retry-after") == "900"
    assert "Rate limit exceeded" in resp_locked.json()["detail"]

    # Verify a different email from a different client IP is not blocked
    other_email = "other.agent@opsdesk.internal"
    resp_other = client.post(
        "/api/auth/login",
        json={"email": other_email, "password": "wrong-pass"},
        headers={"X-Forwarded-For": "198.51.100.42"}
    )
    assert resp_other.status_code == 401


# ============================================================================
# 2. PRE-AUTH X-USER-ID SPOOFING PROTECTION
# ============================================================================
def test_adversarial_preauth_x_user_id_spoofing_protection(client: TestClient, monkeypatch):
    """
    Edge Case 2: An unauthenticated attacker sending arbitrary X-User-Id headers
    cannot exhaust or poison another user's rate limit bucket.
    Middleware keys strictly on client IP before authentication.
    """
    from backend.app import main as main_module
    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 5)

    victim_user_id = "USR-101"

    # Attacker tries to exhaust USR-101's bucket using forged X-User-Id headers
    for i in range(5):
        resp = client.get(
            "/api/tickets?view=triage",
            headers={"X-User-Id": victim_user_id}
        )
        assert resp.status_code != 429

    # 6th request from attacker IP triggers 429
    resp_blocked = client.get(
        "/api/tickets?view=triage",
        headers={"X-User-Id": victim_user_id}
    )
    assert resp_blocked.status_code == 429

    # Verify that the victim's authenticated bucket (user:USR-101) was NOT poisoned
    # Legitimate user authenticating with valid JWT from a different IP succeeds
    legit_token = create_access_token({
        "sub": victim_user_id,
        "email": "aisha.ops@tbo.test",
        "role": "Agent",
        "name": "Aisha Khan"
    })

    # Legitimate user request succeeds with 200 OK
    resp_victim = client.get(
        "/api/tickets?view=my_queue",
        headers={
            "Authorization": f"Bearer {legit_token}",
            "X-Forwarded-For": "203.0.113.50"
        }
    )
    assert resp_victim.status_code == 200, f"Victim request should succeed, got {resp_victim.status_code}"


# ============================================================================
# 3. STREAMING BODY SIZE LIMIT ENFORCEMENT
# ============================================================================
def test_adversarial_streaming_body_size_limit_without_content_length(client: TestClient, monkeypatch):
    """
    Edge Case 3: Streaming a payload exceeding MAX_BODY_BYTES without Content-Length
    (or with chunked/spoofed Content-Length) aborts with HTTP 413 Payload Too Large.
    """
    monkeypatch.setenv("MAX_BODY_BYTES", "1024")

    oversized_data = b"X" * 2048

    # 1. Content-Length exceeding MAX_BODY_BYTES rejected immediately
    resp_cl = client.post(
        "/api/tickets",
        content=oversized_data,
        headers={"Content-Length": str(len(oversized_data)), "Content-Type": "application/json"}
    )
    assert resp_cl.status_code == 413
    assert "Payload Too Large" in resp_cl.json()["detail"]

    # 2. Chunked generator without Content-Length
    def chunk_generator():
        for _ in range(4):
            yield b"Y" * 512

    resp_stream = client.post(
        "/api/tickets",
        content=chunk_generator(),
        headers={"Content-Type": "application/json"}
    )
    assert resp_stream.status_code == 413
    assert "Payload Too Large" in resp_stream.json()["detail"]


# ============================================================================
# 4. SECURITY HEADERS ON ERROR RESPONSES
# ============================================================================
def test_adversarial_security_headers_on_all_error_responses(client: TestClient, monkeypatch):
    """
    Edge Case 4: Verify that X-Content-Type-Options: nosniff, X-Frame-Options: DENY,
    Referrer-Policy: no-referrer, and Cache-Control: no-store are strictly returned
    on 401, 404, 413, and 429 error responses for /api/*.
    """
    monkeypatch.setenv("MAX_BODY_BYTES", "512")

    def assert_security_headers(response, expected_status: int):
        assert response.status_code == expected_status, f"Expected status {expected_status}, got {response.status_code}"
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        assert headers_lower.get("x-content-type-options") == "nosniff", "Missing X-Content-Type-Options: nosniff"
        assert headers_lower.get("x-frame-options") == "DENY", "Missing X-Frame-Options: DENY"
        assert headers_lower.get("referrer-policy") == "no-referrer", "Missing Referrer-Policy: no-referrer"
        assert "no-store" in headers_lower.get("cache-control", ""), f"Missing Cache-Control: no-store, got {headers_lower.get('cache-control')}"

    # 401 Unauthorized
    resp_401 = client.post("/api/auth/login", json={"email": "nobody@test.com", "password": "wrong"})
    assert_security_headers(resp_401, 401)

    # 404 Not Found
    token = create_access_token({"sub": "USR-101", "email": "aisha@tbo.test", "role": "Agent"})
    resp_404 = client.get("/api/tickets/TCK-NONEXISTENT-9999", headers={"Authorization": f"Bearer {token}"})
    assert_security_headers(resp_404, 404)

    # 413 Payload Too Large
    resp_413 = client.post(
        "/api/tickets",
        content=b"A" * 1024,
        headers={"Content-Length": "1024", "Content-Type": "application/json"}
    )
    assert_security_headers(resp_413, 413)

    # 429 Too Many Requests (trigger via login failure bucket)
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "flood@test.com", "password": "wrong"})
    resp_429 = client.post("/api/auth/login", json={"email": "flood@test.com", "password": "wrong"})
    assert_security_headers(resp_429, 429)
