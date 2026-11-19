import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app import main as main_module


@pytest.mark.slow
def test_rate_limit_ip_rotation_contradiction_resolution(client: TestClient, monkeypatch):
    """
    Lane B1: Verifies that when sending 150 requests from a single client IP
    rotating across 4 different X-User-Id headers with RATE_LIMIT_PER_MINUTE=120,
    the IP-based rate limit correctly triggers after 120 requests, yielding
    exactly 120x 200s and 30x 429s.
    """
    # Set limit to 120
    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 120)

    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    user_ids = ["USR-101", "USR-102", "USR-103", "USR-104"]
    status_counts = {}

    try:
        for i in range(150):
            user_id = user_ids[i % len(user_ids)]
            resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
            status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1

        print("\n[RAW B1 COUNTS] 150 requests from single IP with 4 rotating users:", status_counts)

        # Exactly 120 requests succeed before IP threshold is breached
        assert status_counts.get(200, 0) == 120, f"Expected 120x 200 OK, got {status_counts}"
        assert status_counts.get(429, 0) == 30, f"Expected 30x 429 Too Many Requests, got {status_counts}"
    finally:
        with main_module._rate_limit_lock:
            main_module._rate_limit_records.clear()
