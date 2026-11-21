import io
import os
import json
import uuid
import logging
import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.auth import create_access_token


@pytest.fixture(autouse=True)
def clean_rate_limit_state():
    yield
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()


def test_client_supplied_x_user_id_ignored_before_auth(client: TestClient, monkeypatch):
    """
    2.2 In opsdesk_protection_middleware:
    Must NOT use client-supplied X-User-Id header as a bucket key before authentication.
    Before auth, key strictly on ip:{client_ip}.
    """
    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 5)

    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    try:
        # Client tries to spoof rate limit by rotating X-User-Id headers on a non-auth or auth endpoint
        responses = []
        for i in range(10):
            user_id = f"SPOOFED-USER-{i}"
            # Even if client sends unverified X-User-Id, middleware keys strictly on ip:{client_ip}
            resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
            responses.append(resp.status_code)

        # First 5 should reach endpoint (getting 401 because user is unauthenticated/spoofed),
        # but 6th onwards MUST be rate limited (429) at middleware level by client IP!
        assert responses[:5] == [401, 401, 401, 401, 401]
        assert responses[5:] == [429, 429, 429, 429, 429]
    finally:
        with main_module._rate_limit_lock:
            main_module._rate_limit_records.clear()


def test_authenticated_jwt_keys_on_user_id(client: TestClient, monkeypatch):
    """
    2.2 After authentication via JWT, key on user:{user_id}.
    """
    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 3)

    # Use seeded users USR-101 and USR-102
    token1 = create_access_token({"sub": "USR-101", "email": "alex.chen@travelcorp.com", "role": "Agent"})
    token2 = create_access_token({"sub": "USR-102", "email": "sarah.connor@travelcorp.com", "role": "Agent"})

    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    try:
        # User 1 makes 3 requests -> allowed
        for _ in range(3):
            r = client.get("/api/tickets?view=triage", headers={"Authorization": f"Bearer {token1}"})
            assert r.status_code == 200

        # User 1 4th request -> blocked
        r_blocked = client.get("/api/tickets?view=triage", headers={"Authorization": f"Bearer {token1}"})
        assert r_blocked.status_code == 429

        # User 2 makes a request with their own JWT -> allowed (keyed on user:USR-102)
        r2 = client.get("/api/tickets?view=triage", headers={"Authorization": f"Bearer {token2}"})
        assert r2.status_code == 200
    finally:
        with main_module._rate_limit_lock:
            main_module._rate_limit_records.clear()


def test_json_log_lines_with_quotes_and_newlines_in_headers(client: TestClient, caplog):
    """
    2.2 All log lines across middleware and app must be built using json.dumps(...).
    Test: a header containing quotes and newlines (X-Request-ID: test"with\\nquotes)
    does not break the JSON log line (can be parsed with json.loads).
    """
    malformed_header = 'test"with\nquotes\\and"special:chars'
    access_logger = logging.getLogger("opsdesk.access")
    access_logger.disabled = False
    access_logger.setLevel(logging.INFO)
    with caplog.at_level(logging.INFO, logger="opsdesk.access"):
        resp = client.get("/health", headers={"X-Request-ID": malformed_header})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == malformed_header

        # Verify all captured log records that look like JSON can be parsed cleanly
        json_logs_found = 0
        for record in caplog.records:
            msg = record.message.strip()
            if msg.startswith("{") and msg.endswith("}"):
                parsed = json.loads(msg)  # Will raise json.JSONDecodeError if broken
                if "request_id" in parsed:
                    json_logs_found += 1
                    assert parsed["request_id"] == malformed_header

        assert json_logs_found > 0, "Expected at least one request log with the tested X-Request-ID"


def test_api_security_headers(client: TestClient):
    """
    2.5 In middleware, add headers to all responses (or /api/*):
      X-Content-Type-Options: nosniff
      Referrer-Policy: no-referrer
      X-Frame-Options: DENY
      Cache-Control: no-store for any path starting with /api/.
    """
    # 1. API endpoint
    resp_api = client.get("/api/tickets", headers={"X-User-Id": "USR-101"})
    assert resp_api.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_api.headers.get("Referrer-Policy") == "no-referrer"
    assert resp_api.headers.get("X-Frame-Options") == "DENY"
    assert resp_api.headers.get("Cache-Control") == "no-store"

    # 2. Non-API endpoint (e.g. /health)
    resp_health = client.get("/health")
    assert resp_health.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_health.headers.get("Referrer-Policy") == "no-referrer"
    assert resp_health.headers.get("X-Frame-Options") == "DENY"


def test_request_body_size_limit_content_length(client: TestClient, monkeypatch):
    """
    2.5 Request body size limit middleware:
    Env MAX_BODY_BYTES, default 1048576 (1MB).
    Check Content-Length header; if > MAX_BODY_BYTES return 413 Payload Too Large.
    """
    monkeypatch.setenv("MAX_BODY_BYTES", "100")

    # Send body with Content-Length > 100 bytes
    large_payload = {"notes": "x" * 200}
    resp = client.post("/api/tickets", json=large_payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 413
    assert "Payload Too Large" in resp.json()["detail"]
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_request_body_size_limit_streaming(client: TestClient, monkeypatch):
    """
    2.5 Enforce while streaming request body if Content-Length is missing or spoofed
    (streaming byte counter > MAX_BODY_BYTES -> 413).
    """
    monkeypatch.setenv("MAX_BODY_BYTES", "150")

    def streaming_generator():
        # Yield chunks that total more than 150 bytes
        for _ in range(10):
            yield b'{"chunk": "data_chunk_of_bytes_12345"}'

    resp = client.post(
        "/api/tickets",
        content=streaming_generator(),
        headers={"X-User-Id": "USR-101", "Content-Type": "application/json"}
    )
    assert resp.status_code == 413
    assert "Payload Too Large" in resp.json()["detail"]
