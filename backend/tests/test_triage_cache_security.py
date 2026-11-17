import pytest
from backend.app.main import app, _triage_cache, _triage_cache_lock, invalidate_triage_cache

def test_cache_agency_isolation(client):
    """(i) Agency A Requester ka cached result Agency B Requester ko na mile."""
    invalidate_triage_cache()

    # Requester 201 is from AGY-001
    res_a = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-201"})
    assert res_a.status_code == 200
    data_a = res_a.json()
    for t in data_a.get("tickets", []):
        assert t["agency_id"] == "AGY-001"

    # Requester 202 is from AGY-002
    res_b = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-202"})
    assert res_b.status_code == 200
    data_b = res_b.json()
    for t in data_b.get("tickets", []):
        assert t["agency_id"] == "AGY-002"

    with _triage_cache_lock:
        keys = list(_triage_cache.keys())
        key_a = [k for k in keys if "AGY-001" in k]
        key_b = [k for k in keys if "AGY-002" in k]
        assert len(key_a) == 1
        assert len(key_b) == 1
        assert key_a != key_b

def test_cache_staff_vs_requester_role_isolation(client):
    """(ii) Staff ka result Requester ko na mile (internal fields: queue score, routing reason)."""
    invalidate_triage_cache()

    # 1. Staff (Agent USR-101) populates cache
    res_staff = client.get("/api/tickets?view=triage&limit=5", headers={"X-User-Id": "USR-101"})
    assert res_staff.status_code == 200
    data_staff = res_staff.json()
    assert len(data_staff["tickets"]) > 0
    first_staff_ticket = data_staff["tickets"][0]
    # Staff must see queue_score and routing_reason (or they are permitted)
    assert first_staff_ticket.get("queue_score") is not None

    # 2. Requester (USR-201) immediately fetches triage
    res_req = client.get("/api/tickets?view=triage&limit=5", headers={"X-User-Id": "USR-201"})
    assert res_req.status_code == 200
    data_req = res_req.json()
    for t in data_req["tickets"]:
        # Requesters MUST NEVER receive internal queue_score or routing_reason
        assert t.get("queue_score") is None
        assert t.get("routing_reason") is None

def test_cache_invalidation_on_writes(client):
    """(iii) write ke baad (create, assign, status) cache invalidate ho (read-your-writes)."""
    invalidate_triage_cache()

    # Populate cache
    res1 = client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    assert res1.status_code == 200
    with _triage_cache_lock:
        assert len(_triage_cache) > 0

    # 1. Create ticket invalidates cache
    create_payload = {
        "title": "Cache invalidation test ticket",
        "description": "Validating cache invalidation on ticket creation",
        "tboh_id": "TBOH-99999",
        "priority": "High",
        "check_in_date": "2026-12-01T12:00:00",
        "agency_id": "AGY-001"
    }
    res_create = client.post("/api/tickets", json=create_payload, headers={"X-User-Id": "USR-101"})
    assert res_create.status_code == 201
    created_id = res_create.json()["id"]

    with _triage_cache_lock:
        assert len(_triage_cache) == 0, "Cache should be cleared after create_ticket"

    # Re-populate cache
    client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    with _triage_cache_lock:
        assert len(_triage_cache) > 0

    # 2. Assign ticket invalidates cache
    res_assign = client.post(f"/api/tickets/{created_id}/assign", json={"agent_id": "USR-102"}, headers={"X-User-Id": "USR-101"})
    assert res_assign.status_code == 200
    with _triage_cache_lock:
        assert len(_triage_cache) == 0, "Cache should be cleared after assign_ticket"

    # Re-populate cache
    client.get("/api/tickets?view=triage&limit=10", headers={"X-User-Id": "USR-101"})
    with _triage_cache_lock:
        assert len(_triage_cache) > 0

    # 3. Status update invalidates cache
    res_status = client.post(f"/api/tickets/{created_id}/status", json={"status": "Pending"}, headers={"X-User-Id": "USR-101"})
    assert res_status.status_code == 200
    with _triage_cache_lock:
        assert len(_triage_cache) == 0, "Cache should be cleared after update_ticket_status"
