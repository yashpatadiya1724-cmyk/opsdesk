import pytest
import json
import asyncio
from fastapi import status
from backend.app.events import get_broadcaster, Subscriber
from backend.app.models import Ticket, User, EventOutbox, AuditLog


def test_sse_event_stream_greeting_and_disconnect(client):
    """
    Verifies that SSE endpoint /api/events/stream connects cleanly, sends initial
    connected event with user role context, and closes without deadlock.
    """
    headers = {"X-User-Id": "USR-101"}
    with client.stream("GET", "/api/events/stream", headers=headers) as response:
        assert response.status_code == status.HTTP_200_OK
        assert "text/event-stream" in response.headers["Content-Type"]

        lines = []
        for line in response.iter_lines():
            if line:
                lines.append(line)
            if len(lines) >= 2:
                break

        assert "event: connected" in lines[0]
        data = json.loads(lines[1].replace("data: ", ""))
        assert data["status"] == "connected"
        assert data["user_id"] == "USR-101"
        assert data["role"] in ["Agent", "Lead", "EscalationManager"]


def test_sse_event_stream_query_token_auth(client):
    """
    Verifies SSE endpoint accepts authentication via query parameter ?user_id=
    which is essential for native browser EventSource connections.
    """
    with client.stream("GET", "/api/events/stream?user_id=USR-102") as response:
        assert response.status_code == status.HTTP_200_OK
        lines = []
        for line in response.iter_lines():
            if line:
                lines.append(line)
            if len(lines) >= 2:
                break
        assert "event: connected" in lines[0]
        data = json.loads(lines[1].replace("data: ", ""))
        assert data["user_id"] == "USR-102"


def test_sse_realtime_broadcast_and_tenant_isolation(db_session):
    """
    Verifies EventBroadcaster pub-sub logic directly with async queues:
    1. Staff subscriber receives public & internal events across agencies.
    2. Requester subscriber for AGY-001 receives AGY-001 public events.
    3. Requester subscriber NEVER receives internal events or other agencies' events.
    """
    async def _async_runner():
        broadcaster = get_broadcaster()

        # Subscriber 1: Staff Agent
        sub_staff = await broadcaster.subscribe(user_id="USR-101", agency_id=None, role="Agent")
        # Subscriber 2: Requester from AGY-001
        sub_req1 = await broadcaster.subscribe(user_id="USR-201", agency_id="AGY-001", role="Requester")
        # Subscriber 3: Requester from AGY-002
        sub_req2 = await broadcaster.subscribe(user_id="USR-202", agency_id="AGY-002", role="Requester")

        try:
            # Event A: Public event for AGY-001 ticket
            await broadcaster.broadcast(
                event_type="ticket.created",
                ticket_id="TCK-TEST-001",
                agency_id="AGY-001",
                visibility="public",
                payload={"title": "Booking Amendment"}
            )

            # Event B: Internal event for AGY-001 ticket (e.g. internal note)
            await broadcaster.broadcast(
                event_type="message.created",
                ticket_id="TCK-TEST-001",
                agency_id="AGY-001",
                visibility="internal",
                payload={"note": "VIP supplier escalation required"}
            )

            # Event C: Public event for AGY-002 ticket
            await broadcaster.broadcast(
                event_type="ticket.status_changed",
                ticket_id="TCK-TEST-002",
                agency_id="AGY-002",
                visibility="public",
                payload={"status": "Resolved"}
            )

            # Staff should receive all 3 events
            assert sub_staff.queue.qsize() == 3
            evt1 = await sub_staff.queue.get()
            assert evt1["event"] == "ticket.created"
            evt2 = await sub_staff.queue.get()
            assert evt2["visibility"] == "internal"
            evt3 = await sub_staff.queue.get()
            assert evt3["ticket_id"] == "TCK-TEST-002"

            # Requester 1 (AGY-001) should ONLY receive Event A
            assert sub_req1.queue.qsize() == 1
            req1_evt = await sub_req1.queue.get()
            assert req1_evt["event"] == "ticket.created"
            assert req1_evt["agency_id"] == "AGY-001"

            # Requester 2 (AGY-002) should ONLY receive Event C
            assert sub_req2.queue.qsize() == 1
            req2_evt = await sub_req2.queue.get()
            assert req2_evt["event"] == "ticket.status_changed"
            assert req2_evt["agency_id"] == "AGY-002"

        finally:
            await broadcaster.unsubscribe(sub_staff)
            await broadcaster.unsubscribe(sub_req1)
            await broadcaster.unsubscribe(sub_req2)

    asyncio.run(_async_runner())


def test_audit_trail_endpoint_and_sanitization(client, db_session):
    """
    Verifies /api/tickets/{ticket_id}/audit-trail:
    - Returns chronological history with parsed details.
    - Staff receives full audit details.
    - Requester receives sanitized view (internal notes/reasons omitted).
    - Cross-agency access returns 404 Not Found.
    """
    # 1. Grab an existing ticket from AGY-001
    ticket = db_session.query(Ticket).filter(Ticket.agency_id == "AGY-001").first()
    assert ticket is not None

    # Perform a mutation to ensure an audit log entry exists
    assign_res = client.post(
        f"/api/tickets/{ticket.id}/assign",
        json={"agent_id": "USR-101"},
        headers={"X-User-Id": "USR-103"}  # Lead assigns
    )
    assert assign_res.status_code == status.HTTP_200_OK

    # 2. Staff queries audit trail
    res_staff = client.get(
        f"/api/tickets/{ticket.id}/audit-trail?order=desc",
        headers={"X-User-Id": "USR-101"}
    )
    assert res_staff.status_code == status.HTTP_200_OK
    audit_list = res_staff.json()
    assert isinstance(audit_list, list)
    assert len(audit_list) >= 1
    latest = audit_list[0]
    assert "ticket_id" in latest
    assert latest["ticket_id"] == ticket.id
    assert "action" in latest
    assert "details" in latest
    assert isinstance(latest["details"], dict)

    # 3. Requester from same agency queries audit trail
    res_req = client.get(
        f"/api/tickets/{ticket.id}/audit-trail?order=asc",
        headers={"X-User-Id": "USR-201"}  # Requester AGY-001
    )
    assert res_req.status_code == status.HTTP_200_OK
    req_audit = res_req.json()
    # Ensure internal notes or routing reasons are not leaked
    for item in req_audit:
        assert item["action"] != "internal_note_added"
        if isinstance(item.get("details"), dict):
            assert "routing_reason" not in item["details"]

    # 4. Requester from different agency queries audit trail -> 404 Tenant Isolation
    res_cross = client.get(
        f"/api/tickets/{ticket.id}/audit-trail",
        headers={"X-User-Id": "USR-202"}  # Requester AGY-002
    )
    assert res_cross.status_code == status.HTTP_404_NOT_FOUND


def test_prometheus_metrics_endpoint(client):
    """
    Verifies /metrics returns Prometheus text exposition format with operational metrics.
    """
    res = client.get("/metrics")
    assert res.status_code == status.HTTP_200_OK
    assert "text/plain" in res.headers["Content-Type"]
    body = res.text

    assert "# HELP opsdesk_tickets_total" in body
    assert "# TYPE opsdesk_tickets_total gauge" in body
    assert "opsdesk_triage_unassigned_total" in body
    assert "opsdesk_sse_subscribers_active" in body
    assert "opsdesk_db_pool_size" in body
    assert "opsdesk_uptime_seconds" in body


def test_deep_readiness_probe(client):
    """
    Verifies /ready returns structured JSON with DB status, pool stats, queue metrics, and uptime.
    """
    res = client.get("/ready")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert "database_pool" in data
    assert "triage_queue" in data
    assert "unassigned_active" in data["triage_queue"]
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


def test_optimistic_concurrency_control_etag_and_if_match(client, db_session):
    """
    Verifies RFC-compliant ETag & If-Match optimistic concurrency control:
    1. GET /api/tickets/{id} provides ETag header matching ticket.version.
    2. Mutation with matching If-Match header succeeds and increments version.
    3. Mutation with stale If-Match header returns HTTP 409 Conflict.
    4. Mutation with stale payload.version returns HTTP 409 Conflict.
    """
    ticket = db_session.query(Ticket).filter(Ticket.status.in_(["New", "Open"])).first()
    assert ticket is not None

    # 1. GET ticket details and check ETag header
    get_res = client.get(f"/api/tickets/{ticket.id}", headers={"X-User-Id": "USR-101"})
    assert get_res.status_code == status.HTTP_200_OK
    etag = get_res.headers.get("ETag")
    assert etag is not None
    assert f'W/"{ticket.version}"' == etag or f'"{ticket.version}"' == etag

    initial_version = ticket.version

    # 2. Mutate with matching If-Match header
    status_res = client.post(
        f"/api/tickets/{ticket.id}/status",
        json={"status": "Pending"},
        headers={"X-User-Id": "USR-101", "If-Match": etag}
    )
    assert status_res.status_code == status.HTTP_200_OK
    new_version = status_res.json()["version"]
    assert new_version == initial_version + 1

    # 3. Attempt mutation with STALE If-Match header -> 409 Conflict
    stale_res = client.post(
        f"/api/tickets/{ticket.id}/status",
        json={"status": "Open"},
        headers={"X-User-Id": "USR-101", "If-Match": etag}  # Stale initial_version
    )
    assert stale_res.status_code == status.HTTP_409_CONFLICT
    assert "Stale write" in stale_res.json()["detail"]

    # 4. Attempt assign with stale version in payload -> 409 Conflict
    stale_assign = client.post(
        f"/api/tickets/{ticket.id}/assign",
        json={"agent_id": "USR-102", "version": initial_version},
        headers={"X-User-Id": "USR-101"}
    )
    assert stale_assign.status_code == status.HTTP_409_CONFLICT
    assert "Stale write" in stale_assign.json()["detail"]


def test_bulk_assign_tickets_and_audit(client, db_session):
    """
    Verifies POST /api/tickets/bulk-assign:
    - Atomically assigns multiple tickets.
    - Transitions 'New' tickets to 'Open'.
    - Requesters receive HTTP 403 Forbidden.
    """
    tickets = db_session.query(Ticket).filter(Ticket.assigned_to.is_(None)).limit(3).all()
    assert len(tickets) == 3
    ticket_ids = [t.id for t in tickets]

    # Requester attempt -> 403
    req_res = client.post(
        "/api/tickets/bulk-assign",
        json={"ticket_ids": ticket_ids, "agent_id": "USR-101"},
        headers={"X-User-Id": "USR-201"}
    )
    assert req_res.status_code == status.HTTP_403_FORBIDDEN

    # Staff attempt -> 200 OK
    staff_res = client.post(
        "/api/tickets/bulk-assign",
        json={"ticket_ids": ticket_ids, "agent_id": "USR-101"},
        headers={"X-User-Id": "USR-103"}  # Lead
    )
    assert staff_res.status_code == status.HTTP_200_OK
    data = staff_res.json()
    assert data["status"] == "success"
    assert data["total_assigned"] == 3
    assert data["agent_id"] == "USR-101"

    # Verify state in DB
    db_session.expire_all()
    refreshed = db_session.query(Ticket).filter(Ticket.id.in_(ticket_ids)).all()
    for t in refreshed:
        assert t.assigned_to == "USR-101"
        assert t.status in ["Open", "Pending", "Escalated"]


def test_bulk_status_update_with_partial_success(client, db_session):
    """
    Verifies POST /api/tickets/bulk-status:
    - Bulk transitions eligible tickets to new status.
    - Gracefully isolates and reports invalid status transitions in failed_details.
    - Requesters receive HTTP 403 Forbidden.
    """
    ticket1 = db_session.query(Ticket).filter(Ticket.status == "Open").first()
    ticket2 = db_session.query(Ticket).filter(Ticket.status == "Closed").first()
    assert ticket1 is not None and ticket2 is not None

    # Requester attempt -> 403
    req_res = client.post(
        "/api/tickets/bulk-status",
        json={"ticket_ids": [ticket1.id], "status": "Pending"},
        headers={"X-User-Id": "USR-201"}
    )
    assert req_res.status_code == status.HTTP_403_FORBIDDEN

    # Staff attempt with mixed eligible (Open -> Pending) and terminal (Closed -> Pending)
    staff_res = client.post(
        "/api/tickets/bulk-status",
        json={"ticket_ids": [ticket1.id, ticket2.id], "status": "Pending"},
        headers={"X-User-Id": "USR-101"}
    )
    assert staff_res.status_code == status.HTTP_200_OK
    data = staff_res.json()
    assert data["status"] == "partial_success"
    assert data["total_succeeded"] == 1
    assert data["total_failed"] == 1
    assert ticket1.id in data["succeeded_ticket_ids"]
    assert any(f["ticket_id"] == ticket2.id for f in data["failed_details"])


def test_dead_letter_queue_rbac_and_listing(client, db_session):
    """
    Verifies GET /api/admin/outbox/dead-letter:
    - Agents (USR-101), EscalationManagers (USR-103), and Requesters (USR-201) are forbidden (HTTP 403).
    - Leads (USR-104) can list dead-lettered events.
    """
    # Seed a dead-letter event
    ticket = db_session.query(Ticket).first()
    dlq_event = EventOutbox(
        id="EVT-TEST-DLQ-1",
        event_type="ticket_assigned",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="internal",
        payload_json=json.dumps({"ticket_id": ticket.id, "reason": "webhook failed"}),
        status="dead_letter",
        retry_count=5,
        last_error="Connection refused by downstream webhook receiver after 5 retries"
    )
    db_session.add(dlq_event)
    db_session.commit()

    # Agent -> 403
    agent_res = client.get("/api/admin/outbox/dead-letter", headers={"X-User-Id": "USR-101"})
    assert agent_res.status_code == status.HTTP_403_FORBIDDEN

    # EscalationManager -> 403
    esc_res = client.get("/api/admin/outbox/dead-letter", headers={"X-User-Id": "USR-103"})
    assert esc_res.status_code == status.HTTP_403_FORBIDDEN

    # Requester -> 403
    req_res = client.get("/api/admin/outbox/dead-letter", headers={"X-User-Id": "USR-201"})
    assert req_res.status_code == status.HTTP_403_FORBIDDEN

    # Lead -> 200
    lead_res = client.get("/api/admin/outbox/dead-letter", headers={"X-User-Id": "USR-104"})
    assert lead_res.status_code == status.HTTP_200_OK
    data = lead_res.json()
    assert data["total"] >= 1
    matched = [e for e in data["events"] if e["id"] == "EVT-TEST-DLQ-1"]
    assert len(matched) == 1
    assert matched[0]["status"] == "dead_letter"
    assert matched[0]["retry_count"] == 5
    assert "Connection refused" in matched[0]["last_error"]
    assert matched[0]["payload"]["ticket_id"] == ticket.id


def test_dead_letter_retry_single_event(client, db_session):
    """
    Verifies POST /api/admin/outbox/retry/{event_id}:
    - Only Leads (USR-104) can retry an event (403 for Agent/EscalationManager/Requester).
    - 404 for non-existent event.
    - Successfully re-queues event to 'pending' and clears retry count / last_error.
    """
    ticket = db_session.query(Ticket).first()
    dlq_event = EventOutbox(
        id="EVT-TEST-DLQ-RETRY-1",
        event_type="ticket_status_updated",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload_json=json.dumps({"ticket_id": ticket.id}),
        status="dead_letter",
        retry_count=5,
        last_error="HTTP 502 Bad Gateway"
    )
    db_session.add(dlq_event)
    db_session.commit()

    # Non-lead attempt -> 403
    res_403 = client.post("/api/admin/outbox/retry/EVT-TEST-DLQ-RETRY-1", headers={"X-User-Id": "USR-101"})
    assert res_403.status_code == status.HTTP_403_FORBIDDEN

    # Non-existent event -> 404
    res_404 = client.post("/api/admin/outbox/retry/EVT-NON-EXISTENT", headers={"X-User-Id": "USR-104"})
    assert res_404.status_code == status.HTTP_404_NOT_FOUND

    # Lead retry -> 200 OK
    res_200 = client.post("/api/admin/outbox/retry/EVT-TEST-DLQ-RETRY-1", headers={"X-User-Id": "USR-104"})
    assert res_200.status_code == status.HTTP_200_OK
    res_data = res_200.json()
    assert res_data["id"] == "EVT-TEST-DLQ-RETRY-1"
    assert res_data["status"] == "pending"
    assert res_data["retry_count"] == 0

    # Verify DB update
    db_session.expire_all()
    ev = db_session.query(EventOutbox).filter(EventOutbox.id == "EVT-TEST-DLQ-RETRY-1").first()
    assert ev.status == "pending"
    assert ev.retry_count == 0
    assert ev.last_error is None


def test_dead_letter_retry_all(client, db_session):
    """
    Verifies POST /api/admin/outbox/retry-all:
    - Lead (USR-104) can bulk re-queue all dead-lettered events.
    - Verifies count of affected events returned and updated in database.
    """
    ticket = db_session.query(Ticket).first()
    e1 = EventOutbox(
        id="EVT-TEST-BULK-DLQ-1",
        event_type="ticket_created",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload_json="{}",
        status="dead_letter",
        retry_count=3,
        last_error="Timeout"
    )
    e2 = EventOutbox(
        id="EVT-TEST-BULK-DLQ-2",
        event_type="ticket_created",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload_json="{}",
        status="dead_letter",
        retry_count=4,
        last_error="Connection reset"
    )
    db_session.add_all([e1, e2])
    db_session.commit()

    # Agent -> 403
    res_agent = client.post("/api/admin/outbox/retry-all", headers={"X-User-Id": "USR-101"})
    assert res_agent.status_code == status.HTTP_403_FORBIDDEN

    # Lead -> 200 OK
    res = client.post("/api/admin/outbox/retry-all", headers={"X-User-Id": "USR-104"})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["retried_count"] >= 2

    db_session.expire_all()
    reloaded_e1 = db_session.query(EventOutbox).filter(EventOutbox.id == "EVT-TEST-BULK-DLQ-1").first()
    reloaded_e2 = db_session.query(EventOutbox).filter(EventOutbox.id == "EVT-TEST-BULK-DLQ-2").first()
    assert reloaded_e1.status == "pending"
    assert reloaded_e2.status == "pending"


