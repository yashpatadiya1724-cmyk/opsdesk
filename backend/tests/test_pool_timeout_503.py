import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from backend.app.main import app, invalidate_triage_cache
from backend.app.database import get_db

def test_pool_saturation_returns_503_and_recovers(client):
    """
    Verifies that when SQLAlchemy raises TimeoutError (pool checkout exhaustion),
    the server handles it gracefully by returning HTTP 503 with a Retry-After header,
    and subsequent requests succeed normally once connections are available.
    """
    invalidate_triage_cache()

    # 1. Normal request passes
    resp = client.get("/health")
    assert resp.status_code == 200

    # 2. Simulate SQLAlchemy TimeoutError when checking out DB connection
    def failing_get_db():
        raise SQLAlchemyTimeoutError("QueuePool limit of size 30 overflow 20 reached, connection timed out, timeout 5.00")

    original_override = app.dependency_overrides.get(get_db)
    try:
        app.dependency_overrides[get_db] = failing_get_db
        resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "5"
        assert "Database connection pool saturated" in resp.json().get("detail", "")
    finally:
        if original_override:
            app.dependency_overrides[get_db] = original_override
        else:
            app.dependency_overrides.pop(get_db, None)

    # 3. Server recovers immediately for subsequent request
    invalidate_triage_cache()
    resp_after = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
    assert resp_after.status_code == 200
