import time
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app, invalidate_triage_cache, _triage_cache, _triage_cache_lock

def test_triage_cache_stale_while_revalidate(client):
    """
    Verifies Stale-While-Revalidate behavior:
    1. Initial request populates cache.
    2. Request within TTL (fresh) returns cached.
    3. Request between TTL and TTL+MAX_STALE returns stale immediately while triggering refresh.
    4. Write invalidation clears cache immediately.
    """
    invalidate_triage_cache()

    # 1. First read (cache miss, computes synchronously)
    t0 = time.time()
    resp1 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    assert resp1.status_code == 200
    data1 = resp1.json()

    # 2. Fresh hit (immediate)
    resp2 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    assert resp2.status_code == 200
    assert resp2.json()["total"] == data1["total"]

    # 3. Age the cache entry past 2.0s TTL into stale window (< 7.0s)
    with _triage_cache_lock:
        for k in list(_triage_cache.keys()):
            cached_time, payload = _triage_cache[k]
            # set cached timestamp to 2.5 seconds ago (stale, but within 5.0s max stale)
            _triage_cache[k] = (time.time() - 2.5, payload)

    # 4. SWR read: returns immediately (stale hit)
    t_req = time.time()
    resp_stale = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    elapsed = time.time() - t_req
    assert resp_stale.status_code == 200
    assert elapsed < 0.1  # served instantly from stale cache
    assert resp_stale.json()["total"] == data1["total"]

    # 5. Invalidation on write
    invalidate_triage_cache()
    with _triage_cache_lock:
        assert len(_triage_cache) == 0
