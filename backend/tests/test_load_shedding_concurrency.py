import pytest
import asyncio
from fastapi.testclient import TestClient
from backend.app.main import app, set_concurrency_limit, get_concurrency_semaphore, invalidate_triage_cache

def test_concurrency_load_shedding_503_and_health_exempt(client):
    """
    Verifies that:
    1. When in-flight requests saturate the concurrency limit and bounded wait timeout expires,
       excess requests are shed with HTTP 503 and Retry-After: 2 header.
    2. Health check endpoints (/health) are strictly exempt and succeed even under saturation.
    3. Server recovers immediately once active requests complete.
    """
    invalidate_triage_cache()

    # 1. Normal requests pass
    resp = client.get("/health")
    assert resp.status_code == 200
    resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200

    # 2. Configure limit = 1 and short wait timeout = 0.05s for deterministic testing
    set_concurrency_limit(1, wait_timeout=0.05)
    sem = get_concurrency_semaphore()

    # Acquire the single slot to simulate saturated server
    # Run in the same event loop or acquire manually
    loop = asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else asyncio.new_event_loop()
    loop.run_until_complete(sem.acquire())

    try:
        # Non-exempt endpoint must be shed with HTTP 503
        resp_shed = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
        assert resp_shed.status_code == 503
        assert resp_shed.headers.get("Retry-After") == "2"
        assert "Request shed by concurrency limiter" in resp_shed.json().get("detail", "")

        # /health endpoint MUST be exempt and return HTTP 200 even when saturated
        resp_health = client.get("/health")
        assert resp_health.status_code == 200
        assert resp_health.json() == {"status": "healthy", "service": "opsdesk-backend"}

    finally:
        # Release the slot
        sem.release()
        # Restore default concurrency limit
        set_concurrency_limit(60, wait_timeout=2.0)

    # 3. Server recovers immediately
    invalidate_triage_cache()
    resp_recovered = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
    assert resp_recovered.status_code == 200
