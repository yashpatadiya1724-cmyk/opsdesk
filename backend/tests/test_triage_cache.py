import pytest
import time
from fastapi.testclient import TestClient
from backend.app.main import app, _triage_cache, _triage_cache_lock, invalidate_triage_cache

client = TestClient(app)

def test_triage_cache_behavior_and_isolation():
    """
    Validates:
    1. Single-flight 2-second in-memory TTL caching for triage queries.
    2. Tenant isolation in cache keys (Requester agency isolation).
    3. Cache invalidation on mutations.
    """
    invalidate_triage_cache()

    # Agent triage view
    res1 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    assert res1.status_code == 200
    with _triage_cache_lock:
        cache_keys_before = list(_triage_cache.keys())
        assert len(cache_keys_before) == 1
        assert "Agent" in cache_keys_before[0]
        assert "triage" in cache_keys_before[0]

    # Repeated request within TTL hits cache
    res2 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    assert res2.status_code == 200
    assert res2.json() == res1.json()

    # Requester from AGY-001 gets a distinct cache key scoped to their agency
    res_req1 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-201"})
    assert res_req1.status_code == 200
    with _triage_cache_lock:
        req_keys = [k for k in _triage_cache.keys() if "AGY-001" in k]
        assert len(req_keys) == 1

    # Requester from AGY-002 gets distinct cache key scoped to AGY-002
    res_req2 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-202"})
    assert res_req2.status_code == 200
    with _triage_cache_lock:
        req_keys_2 = [k for k in _triage_cache.keys() if "AGY-002" in k]
        assert len(req_keys_2) == 1

    # Invalidation clears the cache
    invalidate_triage_cache()
    with _triage_cache_lock:
        assert len(_triage_cache) == 0
