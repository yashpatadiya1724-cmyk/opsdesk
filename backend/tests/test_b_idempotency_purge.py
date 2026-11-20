import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket, IdempotencyRecord
from backend.app.main import purge_expired_idempotency_records


def test_idempotency_ttl_lazy_and_startup_purge(client: TestClient, db_session: Session, monkeypatch):
    """
    Lane B5: Verifies that Idempotency records older than IDEMPOTENCY_TTL_HOURS
    are purged both via the purge helper and via lazy deletion on access.
    """
    from backend.app import main as main_module
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    # Set TTL to 1 hour
    monkeypatch.setattr(main_module, "IDEMPOTENCY_TTL_HOURS", 1)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=2)

    # 1. Insert an expired idempotency record
    expired_key = f"expired-key-{uuid.uuid4()}"
    expired_record = IdempotencyRecord(
        id=f"USR-201:{expired_key}",
        user_id="USR-201",
        key=expired_key,
        ticket_id="TCK-OLD-IDEM",
        request_hash="mock-hash",
        response_json=json.dumps({"id": "TCK-OLD-IDEM", "status": "Open"}),
        created_at=old_time
    )
    db_session.add(expired_record)
    db_session.commit()

    # Verify present
    rec = db_session.query(IdempotencyRecord).filter(IdempotencyRecord.id == f"USR-201:{expired_key}").first()
    assert rec is not None

    # 2. Test lazy purge on access: attempting to create a ticket with this expired key purges it and creates a new ticket
    payload = {
        "agency_id": "AGY-001",
        "tboh_id": "TBOH-IDEM-PURGE-01",
        "title": "Purge Test Ticket",
        "description": "Testing lazy idempotency TTL",
        "priority": "Medium",
        "check_in_date": (now + timedelta(days=2)).isoformat(),
        "lcd_date": (now + timedelta(hours=12)).isoformat(),
        "first_message": "Hello"
    }

    try:
        resp = client.post(
            "/api/tickets",
            json=payload,
            headers={"X-User-Id": "USR-201", "Idempotency-Key": expired_key}
        )
        assert resp.status_code == 201
        new_ticket_id = resp.json()["id"]
        assert new_ticket_id != "TCK-OLD-IDEM"

        # 3. Test explicit batch purge helper
        stale_key_2 = f"stale-key-2-{uuid.uuid4()}"
        stale_record_2 = IdempotencyRecord(
            id=f"USR-201:{stale_key_2}",
            user_id="USR-201",
            key=stale_key_2,
            ticket_id="TCK-STALE-2",
            request_hash="mock-hash-2",
            response_json=json.dumps({"id": "TCK-STALE-2"}),
            created_at=old_time
        )
        db_session.add(stale_record_2)
        db_session.commit()

        purged_count = purge_expired_idempotency_records(db_session)
        print(f"\n[RAW B5 RESULT] Purged expired idempotency records count: {purged_count}")
        assert purged_count >= 1
    finally:
        # Clean up created test ticket to maintain exact 5000 seed count
        db_session.query(Ticket).filter(Ticket.tboh_id == "TBOH-IDEM-PURGE-01").delete()
        db_session.commit()
        with main_module._rate_limit_lock:
            main_module._rate_limit_records.clear()
