from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket
from backend.app.schemas import TicketCreateSchema, normalize_utc_datetime, to_utc_aware
from backend.services.sla_engine import effective_deadline_hours, evaluate_travel_sla
from backend.services.routing_engine import calculate_queue_score_tier2


def test_schema_dubai_vs_kolkata_offset_parsing():
    """
    Test a hotel in Asia/Dubai (UTC+4) vs Asia/Kolkata (UTC+5:30) with local check-in times.
    Both check-ins are at 14:00 local hotel time on 2026-11-20.
    - Asia/Dubai (UTC+4): 14:00 local is 10:00:00 UTC.
    - Asia/Kolkata (UTC+5:30): 14:00 local is 08:30:00 UTC.
    Verifies parsing of offset ISO strings and storage conversion to UTC.
    """
    base_payload = {
        "title": "Hotel Check-in Timezone Test",
        "description": "Validating local checkin normalization across timezones",
        "priority": "High",
        "intent": "Emergency Check-in Assist",
        "agency_id": "AGY-001"
    }

    # Dubai: 14:00 UTC+4
    payload_dubai = {
        **base_payload,
        "tboh_id": "TBOH-TZ-DXB-01",
        "hotel_timezone": "Asia/Dubai",
        "check_in_date": "2026-11-20T14:00:00+04:00",
        "lcd_date": "2026-11-20T12:00:00+04:00"
    }
    schema_dubai = TicketCreateSchema(**payload_dubai)

    # Kolkata: 14:00 UTC+5:30
    payload_kolkata = {
        **base_payload,
        "tboh_id": "TBOH-TZ-CCU-01",
        "hotel_timezone": "Asia/Kolkata",
        "check_in_date": "2026-11-20T14:00:00+05:30",
        "lcd_date": "2026-11-20T12:00:00+05:30"
    }
    schema_kolkata = TicketCreateSchema(**payload_kolkata)

    # Dubai check_in_date normalized to UTC (10:00)
    expected_dubai_checkin = datetime(2026, 11, 20, 10, 0, 0)
    expected_dubai_lcd = datetime(2026, 11, 20, 8, 0, 0)
    assert schema_dubai.check_in_date.replace(tzinfo=None) == expected_dubai_checkin
    assert schema_dubai.lcd_date.replace(tzinfo=None) == expected_dubai_lcd
    assert schema_dubai.hotel_timezone == "Asia/Dubai"

    # Kolkata check_in_date normalized to UTC (08:30)
    expected_kolkata_checkin = datetime(2026, 11, 20, 8, 30, 0)
    expected_kolkata_lcd = datetime(2026, 11, 20, 6, 30, 0)
    assert schema_kolkata.check_in_date.replace(tzinfo=None) == expected_kolkata_checkin
    assert schema_kolkata.lcd_date.replace(tzinfo=None) == expected_kolkata_lcd
    assert schema_kolkata.hotel_timezone == "Asia/Kolkata"

    # Kolkata checkin is 1.5 hours earlier in UTC than Dubai checkin
    diff_seconds = (schema_dubai.check_in_date - schema_kolkata.check_in_date).total_seconds()
    assert diff_seconds == 5400.0  # exactly 1.5 hours


def test_schema_naive_datetime_with_hotel_timezone():
    """
    Verifies that naive ISO strings without offset are correctly localized to
    the specified hotel_timezone before conversion to UTC.
    """
    base_payload = {
        "title": "Hotel Check-in Naive Local Time Test",
        "description": "Validating naive datetime localization to hotel_timezone",
        "priority": "Medium",
        "intent": "Unclassified",
        "agency_id": "AGY-001"
    }

    # Naive string "2026-11-20T14:00:00" with Asia/Dubai
    schema_dubai = TicketCreateSchema(**{
        **base_payload,
        "tboh_id": "TBOH-TZ-DXB-02",
        "hotel_timezone": "Asia/Dubai",
        "check_in_date": "2026-11-20T14:00:00"
    })
    assert schema_dubai.check_in_date.replace(tzinfo=None) == datetime(2026, 11, 20, 10, 0, 0)

    # Naive string "2026-11-20T14:00:00" with Asia/Kolkata
    schema_kolkata = TicketCreateSchema(**{
        **base_payload,
        "tboh_id": "TBOH-TZ-CCU-02",
        "hotel_timezone": "Asia/Kolkata",
        "check_in_date": "2026-11-20T14:00:00"
    })
    assert schema_kolkata.check_in_date.replace(tzinfo=None) == datetime(2026, 11, 20, 8, 30, 0)

    # Default timezone is UTC when omitted
    schema_utc = TicketCreateSchema(**{
        **base_payload,
        "tboh_id": "TBOH-TZ-UTC-01",
        "check_in_date": "2026-11-20T14:00:00"
    })
    assert schema_utc.hotel_timezone == "UTC"
    assert schema_utc.check_in_date.replace(tzinfo=None) == datetime(2026, 11, 20, 14, 0, 0)


def test_sla_deadline_calculations_in_utc():
    """
    Verifies SLA deadline calculations operate strictly in UTC.
    For local check-in at 14:00:
    - Kolkata check-in is 08:30 UTC
    - Dubai check-in is 10:00 UTC
    At 07:00 UTC:
    - Kolkata has 1.5h remaining (AT_RISK for Medium priority, <= 2.0h threshold)
    - Dubai has 3.0h remaining (NORMAL for Medium priority, > 2.0h threshold)
    """
    kolkata_utc = datetime(2026, 11, 20, 8, 30, 0, tzinfo=timezone.utc)
    dubai_utc = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)

    now_utc = datetime(2026, 11, 20, 7, 0, 0, tzinfo=timezone.utc)

    # Kolkata effective deadline
    hours_kolkata = effective_deadline_hours(
        check_in_date=kolkata_utc,
        lcd_date=None,
        intent="Emergency Check-in Assist",
        now=now_utc
    )
    assert hours_kolkata == pytest.approx(1.5, abs=0.01)

    # Dubai effective deadline
    hours_dubai = effective_deadline_hours(
        check_in_date=dubai_utc,
        lcd_date=None,
        intent="Emergency Check-in Assist",
        now=now_utc
    )
    assert hours_dubai == pytest.approx(3.0, abs=0.01)

    # SLA evaluation
    sla_kolkata = evaluate_travel_sla(
        status="Open",
        check_in_date=kolkata_utc,
        lcd_date=None,
        priority="Medium",
        intent="Emergency Check-in Assist",
        now=now_utc
    )
    assert sla_kolkata["status"] == "AT_RISK"
    assert sla_kolkata["hours_remaining"] == 1.5

    sla_dubai = evaluate_travel_sla(
        status="Open",
        check_in_date=dubai_utc,
        lcd_date=None,
        priority="Medium",
        intent="Emergency Check-in Assist",
        now=now_utc
    )
    assert sla_dubai["status"] == "NORMAL"
    assert sla_dubai["hours_remaining"] == 3.0


def test_api_create_and_get_ticket_with_hotel_timezone(client: TestClient, db_session: Session):
    """
    End-to-end API test:
    1. Creates tickets with hotel_timezone for Dubai and Kolkata.
    2. Verifies HTTP 201 response includes hotel_timezone.
    3. Verifies GET /api/tickets/{id} returns hotel_timezone and UTC check_in_date.
    4. Verifies database storage is UTC.
    5. Verifies GET /api/tickets list includes hotel_timezone.
    """
    # 1. Create Dubai hotel ticket
    resp_dxb = client.post(
        "/api/tickets",
        json={
            "title": "Dubai Hotel Check-in Escalation",
            "description": "Guest requesting early checkin at Dubai marina resort",
            "tboh_id": "TBOH-API-DXB-01",
            "priority": "Medium",
            "intent": "Bedding / Room Preference",
            "agency_id": "AGY-001",
            "hotel_timezone": "Asia/Dubai",
            "check_in_date": "2026-11-20T14:00:00+04:00"
        },
        headers={"X-User-Id": "USR-101"}
    )
    assert resp_dxb.status_code == 201
    data_dxb = resp_dxb.json()
    assert data_dxb["hotel_timezone"] == "Asia/Dubai"
    ticket_id_dxb = data_dxb["id"]

    # 2. Create Kolkata hotel ticket
    resp_ccu = client.post(
        "/api/tickets",
        json={
            "title": "Kolkata Hotel Check-in Request",
            "description": "Late checkin arrival at Kolkata airport hotel",
            "tboh_id": "TBOH-API-CCU-01",
            "priority": "Medium",
            "intent": "Bedding / Room Preference",
            "agency_id": "AGY-001",
            "hotel_timezone": "Asia/Kolkata",
            "check_in_date": "2026-11-20T14:00:00+05:30"
        },
        headers={"X-User-Id": "USR-101"}
    )
    assert resp_ccu.status_code == 201
    data_ccu = resp_ccu.json()
    assert data_ccu["hotel_timezone"] == "Asia/Kolkata"
    ticket_id_ccu = data_ccu["id"]

    # 3. Retrieve Dubai ticket detail
    get_dxb = client.get(f"/api/tickets/{ticket_id_dxb}", headers={"X-User-Id": "USR-101"})
    assert get_dxb.status_code == 200
    detail_dxb = get_dxb.json()
    assert detail_dxb["hotel_timezone"] == "Asia/Dubai"
    # ISO string represents UTC 10:00
    assert "2026-11-20T10:00:00" in detail_dxb["check_in_date"]

    # 4. Retrieve Kolkata ticket detail
    get_ccu = client.get(f"/api/tickets/{ticket_id_ccu}", headers={"X-User-Id": "USR-101"})
    assert get_ccu.status_code == 200
    detail_ccu = get_ccu.json()
    assert detail_ccu["hotel_timezone"] == "Asia/Kolkata"
    # ISO string represents UTC 08:30
    assert "2026-11-20T08:30:00" in detail_ccu["check_in_date"]

    # 5. Verify database storage directly via ORM
    db_dxb = db_session.query(Ticket).filter(Ticket.id == ticket_id_dxb).first()
    assert db_dxb is not None
    assert db_dxb.hotel_timezone == "Asia/Dubai"
    assert db_dxb.check_in_date.hour == 10
    assert db_dxb.check_in_date.minute == 0

    db_ccu = db_session.query(Ticket).filter(Ticket.id == ticket_id_ccu).first()
    assert db_ccu is not None
    assert db_ccu.hotel_timezone == "Asia/Kolkata"
    assert db_ccu.check_in_date.hour == 8
    assert db_ccu.check_in_date.minute == 30

    # 6. Verify list endpoint returns hotel_timezone (search by tboh_id)
    list_dxb = client.get(f"/api/tickets?search={data_dxb['tboh_id']}", headers={"X-User-Id": "USR-101"})
    assert list_dxb.status_code == 200
    tickets_dxb = list_dxb.json()["tickets"]
    assert len(tickets_dxb) >= 1
    assert tickets_dxb[0]["id"] == ticket_id_dxb
    assert tickets_dxb[0]["hotel_timezone"] == "Asia/Dubai"

    list_ccu = client.get(f"/api/tickets?search={data_ccu['tboh_id']}", headers={"X-User-Id": "USR-101"})
    assert list_ccu.status_code == 200
    tickets_ccu = list_ccu.json()["tickets"]
    assert len(tickets_ccu) >= 1
    assert tickets_ccu[0]["id"] == ticket_id_ccu
    assert tickets_ccu[0]["hotel_timezone"] == "Asia/Kolkata"


def test_no_naive_aware_datetime_comparison_errors():
    """
    Stress-tests mixing naive and aware datetimes across all core SLA, routing,
    and database operations to guarantee no TypeError is ever raised.
    """
    naive_dt = datetime(2026, 11, 20, 10, 0, 0)
    aware_dt = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)

    # 1. effective_deadline_hours: naive check_in with aware now
    h1 = effective_deadline_hours(naive_dt, None, "Unclassified", aware_dt)
    assert h1 == 0.0

    # 2. effective_deadline_hours: aware check_in with naive now
    h2 = effective_deadline_hours(aware_dt, None, "Unclassified", naive_dt)
    assert h2 == 0.0

    # 3. evaluate_travel_sla: naive check_in with aware now
    sla1 = evaluate_travel_sla("Open", naive_dt, None, "Medium", now=aware_dt)
    assert sla1["status"] in ["BREACHED", "AT_RISK", "NORMAL"]

    # 4. evaluate_travel_sla: aware check_in with naive now
    sla2 = evaluate_travel_sla("Open", aware_dt, None, "Medium", now=naive_dt)
    assert sla2["status"] in ["BREACHED", "AT_RISK", "NORMAL"]

    # 5. calculate_queue_score_tier2: naive check_in with aware now
    qs1 = calculate_queue_score_tier2("Medium", naive_dt, now=aware_dt)
    assert isinstance(qs1, float)

    # 6. calculate_queue_score_tier2: aware check_in with naive now
    qs2 = calculate_queue_score_tier2("Medium", aware_dt, now=naive_dt)
    assert isinstance(qs2, float)

    # 7. to_utc_aware handles None, naive, aware
    assert to_utc_aware(None) is None
    assert to_utc_aware(naive_dt).tzinfo == timezone.utc
    assert to_utc_aware(aware_dt).tzinfo == timezone.utc


def test_store_aware_datetime_and_read_back_equal_in_utc(db_session: Session):
    """
    Verifies that storing a timezone-aware datetime with an explicit offset
    persists correctly and reads back exactly equal in UTC (to_utc_aware).
    """
    from zoneinfo import ZoneInfo
    dubai_tz = ZoneInfo("Asia/Dubai")  # UTC+04:00
    aware_checkin = datetime(2026, 12, 1, 15, 0, 0, tzinfo=dubai_tz)
    expected_utc = datetime(2026, 12, 1, 11, 0, 0, tzinfo=timezone.utc)

    ticket = Ticket(
        id="TCK-TZ-STORE-TEST",
        tboh_id="TBOH-TZ-STORE",
        agency_id="AGY-001",
        title="Timezone Storage Precision Test",
        description="Verify aware datetime persistence and UTC read-back",
        priority="Medium",
        status="New",
        check_in_date=aware_checkin,
        hotel_timezone="Asia/Dubai",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db_session.add(ticket)
    db_session.commit()

    db_session.expire_all()
    loaded = db_session.query(Ticket).filter(Ticket.id == "TCK-TZ-STORE-TEST").first()
    assert loaded is not None

    loaded_utc = to_utc_aware(loaded.check_in_date)
    assert loaded_utc == expected_utc
    assert loaded_utc.tzinfo == timezone.utc
    assert loaded_utc.isoformat() == "2026-12-01T11:00:00+00:00"
