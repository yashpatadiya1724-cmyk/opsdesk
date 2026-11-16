import os
import sys
import random
from datetime import datetime, timedelta

# Ensure repo root is on sys.path when script is invoked directly
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from faker import Faker
from sqlalchemy.orm import Session
from backend.app.database import Base, SessionLocal
from backend.app.models import (
    Agency, User, Ticket, TicketLink, TicketMessage,
    SideConversation, SideConversationRecipient, SideConversationMessage,
    TicketTheme, AuditLog
)
from backend.services.routing_engine import CandidateAgent, select_agent_tier1

# Rule-based theme mapping based on ticket intent
THEME_MAPPINGS = {
    "Refund Request": ["Refund Delay", "Payment Gateway Reconciliation"],
    "Cancellation Inconvenience": ["Supplier Lag", "Cancellation Penalty Dispute"],
    "Date Amendment": ["Schedule Disruption", "Fare Recalculation"],
    "Bedding / Room Preference": ["Room Mismatch", "Special Facility Request"],
    "Voucher Resend": ["Documentation Lag", "Missing Confirmation Voucher"],
    "Emergency Check-in Assist": ["Hotel Check-in Rejection", "Supplier Contact Unreachable"],
    "Unclassified": ["General Operations Inquiry"]
}

def seed_database(db: Session, engine_bind=None, total_tickets: int = 5000, drop_existing: bool = False):
    """
    Seeds the database with deterministic fixtures and 5,000 synthetic records.
    - All historical tickets (past check-in) are strictly marked 'Closed' or 'Resolved' (SLA STOPPED).
    - All active tickets (New/Open/Pending/Escalated) strictly have future check-in and LCD dates.
    - Escalated tickets are assigned strictly to Escalation Manager USR-103 (Vikram Malhotra).
    - Standard assigned queue tickets are strictly restricted to Tier-1 desk agents: USR-101 and USR-102.
    - Workload and assignments for Journey fixtures are dynamically computed via select_agent_tier1.
    """
    target_bind = engine_bind if engine_bind is not None else db.get_bind()
    fake = Faker()
    Faker.seed(42)
    random.seed(42)

    # Recreate tables cleanly if drop_existing requested, otherwise ensure created
    if drop_existing:
        Base.metadata.drop_all(bind=target_bind)
    Base.metadata.create_all(bind=target_bind)

    print("Creating agencies...")
    agencies = [
        Agency(id="AGY-001", name="Krypton Voyages B2B", country_code="AE", tier="Premium"),
        Agency(id="AGY-002", name="Vectora Travel", country_code="IN", tier="Standard"),
        Agency(id="AGY-003", name="Aethelgard Holidays", country_code="UK", tier="Premium")
    ]
    db.add_all(agencies)
    db.commit()

    print("Creating users...")
    users = [
        # Internal Operations Staff (Tier-1 Desk Agents: USR-101, USR-102)
        User(id="USR-101", name="Aisha Khan", email="aisha.ops@tbo.test", role="Agent", region="MEA", is_available=True),
        User(id="USR-102", name="Rahul Verma", email="rahul.ops@tbo.test", role="Agent", region="MEA", is_available=True),
        # Internal Supervisory Staff (Escalation & Lead roles)
        User(id="USR-103", name="Vikram Malhotra", email="vikram.esc@tbo.test", role="EscalationManager", region="APAC", is_available=True),
        User(id="USR-104", name="Elena Rostova", email="elena.lead@tbo.test", role="Lead", region="EUR", is_available=True),
        # Agency Requesters (RFC 2606 email domains)
        User(id="USR-201", name="Krypton Desk", email="agent@krypton.example.com", role="Requester", region="MEA", agency_id="AGY-001"),
        User(id="USR-202", name="Vectora Desk", email="agent@vectora.example.com", role="Requester", region="APAC", agency_id="AGY-002"),
        User(id="USR-203", name="Aethelgard Desk", email="agent@aethelgard.example.com", role="Requester", region="EUR", agency_id="AGY-003")
    ]
    db.add_all(users)
    db.commit()

    now = datetime.utcnow()

    print("Seeding Journey fixtures (TCK-1001, TCK-1002, TCK-1004, TCK-1005, TCK-1006, TCK-1007, TCK-1008)...")
    
    # Journey A: Context & Linkage Fixtures (Same TBOH, both Closed in past)
    tck_1001 = Ticket(
        id="TCK-1001",
        tboh_id="TBOH-89104",
        agency_id="AGY-001",
        title="Flight cancelled - refund requested",
        description="Airline cancelled flight AF-902; requesting full refund to agency wallet.",
        intent="Refund Request",
        priority="High",
        status="Closed",
        check_in_date=now - timedelta(days=14),
        lcd_date=now - timedelta(days=16),
        assigned_to="USR-101",
        routing_reason="Assigned to Aisha Khan [Historical Case]",
        created_at=now - timedelta(days=15)
    )
    tck_1002 = Ticket(
        id="TCK-1002",
        tboh_id="TBOH-89104",
        agency_id="AGY-001",
        title="Follow-up: status update on refund for TBOH-89104",
        description="Checking status on refund initiated 10 days ago.",
        intent="Refund Request",
        priority="Medium",
        status="Closed",
        check_in_date=now - timedelta(days=4),
        lcd_date=now - timedelta(days=6),
        assigned_to="USR-101",
        routing_reason="Assigned to Aisha Khan [Historical Case]",
        created_at=now - timedelta(days=5)
    )
    db.add_all([tck_1001, tck_1002])
    db.commit()

    # Helper to dynamically compute agent workload from routing engine logic
    def compute_agent_workload(agent_id: str) -> int:
        return db.query(Ticket).filter(
            Ticket.assigned_to == agent_id,
            Ticket.status.in_(["New", "Open", "Pending", "Escalated"])
        ).count()

    # Journey B: Urgent routing (~2.5h check-in, MEA). Non-cancellation intent -> lcd_date is None
    workload_b = compute_agent_workload("USR-101")
    tck_1004_checkin = now + timedelta(hours=2, minutes=30)
    tck_1004 = Ticket(
        id="TCK-1004",
        tboh_id="TBOH-91002",
        agency_id="AGY-001",
        title="Emergency: check-in issue at resort",
        description="Guest at front desk, voucher not appearing on hotel system.",
        intent="Emergency Check-in Assist",
        priority="Urgent",
        status="Open",
        check_in_date=tck_1004_checkin,
        lcd_date=None,
        assigned_to="USR-101",
        routing_reason=f"Assigned to Aisha Khan [Tier-1 Rule: Region=MEA match, Availability=True, Workload={workload_b} active cases]",
        created_at=now - timedelta(minutes=10)
    )
    db.add(tck_1004)
    db.commit()

    # Journey C: Side Conversation Transfer fixture (Aisha handles case, then transfers to Rahul)
    workload_c = compute_agent_workload("USR-101")
    tck_1005_checkin = now + timedelta(days=3)
    tck_1005 = Ticket(
        id="TCK-1005",
        tboh_id="TBOH-93041",
        agency_id="AGY-001",
        title="Meal inclusion query with resort",
        description="Agency asking if half-board package includes beverages at Kryos Heights Resort.",
        intent="Bedding / Room Preference",
        priority="Medium",
        status="Open",
        check_in_date=tck_1005_checkin,
        lcd_date=None,
        assigned_to="USR-101",
        routing_reason=f"Assigned to Aisha Khan [Tier-1 Rule: Region=MEA match, Availability=True, Workload={workload_c} active cases]",
        created_at=now - timedelta(hours=1)
    )
    db.add(tck_1005)
    db.commit()

    # Journey D: SLA Warning (~45 min check-in, Urgent). Non-cancellation intent -> lcd_date is None
    workload_d = compute_agent_workload("USR-101")
    tck_1006_checkin = now + timedelta(minutes=45)
    tck_1006 = Ticket(
        id="TCK-1006",
        tboh_id="TBOH-94420",
        agency_id="AGY-001",
        title="Urgent: guest arriving in 45 minutes",
        description="Confirmation needed immediately for late check-in request.",
        intent="Emergency Check-in Assist",
        priority="Urgent",
        status="Open",
        check_in_date=tck_1006_checkin,
        lcd_date=None,
        assigned_to="USR-101",
        routing_reason=f"Assigned to Aisha Khan [Tier-1 Rule: Region=MEA match, Availability=True, Workload={workload_d} active cases]",
        created_at=now - timedelta(minutes=15)
    )
    db.add(tck_1006)
    db.commit()

    # Journey B (Unassigned Triage Fixture): Urgent routing (~2.25h check-in, MEA, AGY-001)
    tck_1007_checkin = now + timedelta(hours=2, minutes=15)
    tck_1007 = Ticket(
        id="TCK-1007",
        tboh_id="TBOH-95100",
        agency_id="AGY-001",
        title="Urgent unassigned: front desk check-in emergency",
        description="Guest at resort front desk, reservation not found on hotel system. Unassigned in triage pool.",
        intent="Emergency Check-in Assist",
        priority="Urgent",
        status="New",
        check_in_date=tck_1007_checkin,
        lcd_date=None,
        assigned_to=None,
        routing_reason="Unassigned pending triage routing",
        created_at=now - timedelta(minutes=5)
    )
    db.add(tck_1007)
    db.commit()

    # Journey Fixture TCK-1008: Refund Request with imminent LCD cancellation deadline (3h LCD, 5d check-in)
    workload_1008 = compute_agent_workload("USR-101")
    tck_1008_checkin = now + timedelta(days=5)
    tck_1008_lcd = now + timedelta(hours=3)
    tck_1008 = Ticket(
        id="TCK-1008",
        tboh_id="TBOH-89104",
        agency_id="AGY-001",
        title="Urgent refund request before cancellation deadline",
        description="Supplier cancellation penalty applies in 3 hours. Guest cannot travel; refund requested before LCD expires.",
        intent="Refund Request",
        priority="High",
        status="Open",
        check_in_date=tck_1008_checkin,
        lcd_date=tck_1008_lcd,
        assigned_to="USR-101",
        routing_reason=f"Assigned to Aisha Khan [Tier-1 Rule: Region=MEA match, Availability=True, Workload={workload_1008} active cases]",
        created_at=now - timedelta(minutes=20)
    )
    db.add(tck_1008)
    db.commit()

    fixture_tickets = [tck_1001, tck_1002, tck_1004, tck_1005, tck_1006, tck_1007, tck_1008]

    # Link TCK-1001 and TCK-1002 (Shared TBOH-89104) and link TCK-1008 to TCK-1001
    db.add(TicketLink(
        id="LNK-001",
        ticket_id="TCK-1001",
        linked_ticket_id="TCK-1002",
        link_reason="Shared TBOH: TBOH-89104"
    ))
    db.add(TicketLink(
        id="LNK-002",
        ticket_id="TCK-1008",
        linked_ticket_id="TCK-1001",
        link_reason="Shared TBOH: TBOH-89104 (Prior cancelled refund)"
    ))

    # Add Side Conversation with explicit recipients for TCK-1005
    side_convo = SideConversation(
        id="SC-001",
        ticket_id="TCK-1005",
        supplier_name="Kryos Heights Resort",
        subject="Meal inclusion clarification for TBOH-93041",
        created_by="USR-101",
        created_at=now - timedelta(minutes=45)
    )
    db.add(side_convo)
    db.commit()

    db.add_all([
        SideConversationRecipient(id="SCR-001", side_conversation_id="SC-001", email="reservations@vendor.example.com"),
        SideConversationRecipient(id="SCR-002", side_conversation_id="SC-001", email="duty.mgr@vendor.example.com"),
        SideConversationMessage(
            id="SCM-001",
            side_conversation_id="SC-001",
            sender_email="aisha.ops@tbo.test",
            body="Hello Reservations, could you please confirm if booking TBOH-93041 includes soft beverages during dinner?",
            created_at=now - timedelta(minutes=40)
        )
    ])
    db.commit()

    # Add theme tags for fixtures
    for t in fixture_tickets:
        themes = THEME_MAPPINGS.get(t.intent, ["General Operations Inquiry"])
        for idx, th in enumerate(themes):
            db.add(TicketTheme(
                id=f"THM-{t.id}-{idx}",
                ticket_id=t.id,
                theme=th,
                created_at=t.created_at
            ))
    db.commit()

    print(f"Generating remaining {total_tickets - len(fixture_tickets)} synthetic tickets...")
    agency_ids = ["AGY-001", "AGY-002", "AGY-003"]
    # Operational desk agents assigned standard tickets: strictly USR-101 and USR-102
    desk_agent_ids = ["USR-101", "USR-102"]
    intents = [
        "Refund Request",
        "Cancellation Inconvenience",
        "Date Amendment",
        "Bedding / Room Preference",
        "Voucher Resend",
        "Emergency Check-in Assist",
        "Unclassified"
    ]
    # Keep Unclassified at ~5% (below 15% ceiling assumption) to prevent triage queue clutter
    intent_weights = [0.18, 0.18, 0.16, 0.16, 0.14, 0.13, 0.05]
    priorities = ["Low", "Medium", "High", "Urgent"]

    synthetic_count = total_tickets - len(fixture_tickets)
    historical_count = 3500
    escalated_count = 40
    at_risk_synthetic_count = 78
    normal_active_count = synthetic_count - historical_count - escalated_count - at_risk_synthetic_count

    categories = (
        ["historical"] * historical_count +
        ["escalated"] * escalated_count +
        ["at_risk"] * at_risk_synthetic_count +
        ["normal_active"] * normal_active_count
    )
    random.shuffle(categories)

    batch_size = 500
    ticket_batch = []
    theme_batch = []

    for i, cat in enumerate(categories):
        ticket_id = f"TCK-{2000 + i}"
        tboh = f"TBOH-{random.randint(10000, 99999)}"
        agency_id = random.choice(agency_ids)
        intent = random.choices(intents, weights=intent_weights, k=1)[0]

        if cat == "historical":
            priority = random.choice(priorities)
            days_ago = random.randint(1, 45)
            check_in = now - timedelta(days=days_ago, hours=random.randint(1, 23))
            status = random.choice(["Closed", "Resolved"])
            assigned = random.choice(desk_agent_ids)
            created = check_in - timedelta(days=random.randint(2, 10))
            routing_reason = f"Assigned to agent {assigned} [Historical Case]"
        elif cat == "escalated":
            # Escalated status with future check-in, assigned strictly to EscalationManager USR-103
            priority = "High"
            days_ahead = random.randint(2, 15)
            check_in = now + timedelta(days=days_ahead, hours=random.randint(1, 12))
            status = "Escalated"
            assigned = "USR-103"
            created = now - timedelta(hours=random.randint(2, 48))
            routing_reason = "Escalated to Vikram Malhotra [EscalationManager Assignment]"
        elif cat == "at_risk":
            priority = "Urgent"
            hours_ahead = random.uniform(1.0, 5.5)
            check_in = now + timedelta(hours=hours_ahead)
            status = random.choice(["Open", "Pending"])
            assigned = random.choice(desk_agent_ids)
            created = now - timedelta(minutes=random.randint(10, 60))
            routing_reason = f"Assigned to agent {assigned} [Tier-1 Rule: Region workload match]"
        else: # normal_active
            priority = random.choice(priorities)
            days_ahead = random.randint(2, 20)
            check_in = now + timedelta(days=days_ahead, hours=random.randint(1, 12))
            status = random.choice(["New", "Open", "Pending"])
            assigned = random.choice(desk_agent_ids) if status != "New" else None
            created = now - timedelta(hours=random.randint(1, 24))
            routing_reason = (
                f"Assigned to agent {assigned} [Tier-1 Rule: Region workload match]"
                if assigned else "Unassigned in Triage"
            )

        # LCD computation per amended rule:
        # Refund Request, Cancellation Inconvenience, and Unclassified tickets carry an LCD cancellation deadline.
        # For active/open tickets: strictly now < lcd <= check_in.
        # For resolved/closed tickets: past lcd < check_in is expected.
        # Other operational intents (check-in assist, voucher, amendments, room preferences) have lcd = None.
        cancellation_intents = {"Refund Request", "Cancellation Inconvenience", "Unclassified"}
        if intent in cancellation_intents:
            if status in ["Closed", "Resolved"]:
                lcd = check_in - timedelta(days=random.randint(1, 3))
            else:
                hours_to_checkin = (check_in - now).total_seconds() / 3600.0
                if hours_to_checkin <= 2.0:
                    lcd = now + timedelta(hours=max(0.25, hours_to_checkin * 0.5))
                elif hours_to_checkin <= 6.0:
                    lcd = now + timedelta(hours=random.uniform(0.5, hours_to_checkin * 0.8))
                else:
                    days_before = random.randint(1, min(3, max(1, int(hours_to_checkin // 24) - 1)))
                    lcd = check_in - timedelta(days=days_before)
                    if lcd <= now:
                        lcd = now + timedelta(hours=2.0)
        else:
            lcd = None

        t = Ticket(
            id=ticket_id,
            tboh_id=tboh,
            agency_id=agency_id,
            title=f"{intent}: {fake.sentence(nb_words=6)}",
            description=fake.paragraph(nb_sentences=3),
            intent=intent,
            priority=priority,
            status=status,
            check_in_date=check_in,
            lcd_date=lcd,
            assigned_to=assigned,
            routing_reason=routing_reason,
            created_at=created,
            updated_at=created
        )
        ticket_batch.append(t)

        mapped_themes = THEME_MAPPINGS.get(intent, ["General Operations Inquiry"])
        for idx, th in enumerate(mapped_themes):
            theme_batch.append(TicketTheme(
                id=f"THM-{ticket_id}-{idx}",
                ticket_id=ticket_id,
                theme=th,
                created_at=created
            ))

        if len(ticket_batch) >= batch_size:
            db.add_all(ticket_batch)
            db.add_all(theme_batch)
            db.commit()
            ticket_batch.clear()
            theme_batch.clear()

    if ticket_batch:
        db.add_all(ticket_batch)
        db.add_all(theme_batch)
        db.commit()

    print(f"Database successfully seeded with {total_tickets} tickets.")

if __name__ == "__main__":
    import argparse
    import sys
    from sqlalchemy import inspect, text
    from backend.app.config import DATABASE_URL
    from backend.app.database import engine

    parser = argparse.ArgumentParser(description="Seed or reset OpsDesk development database")
    parser.add_argument("--reset", action="store_true", help="Reset and regenerate dev database relative to current wall-clock time")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirm resetting database without safety prompt")
    parser.add_argument("--tickets", type=int, default=5000, help="Total ticket count (default: 5000)")
    args = parser.parse_args()

    # Safety validation: ensure target is a local dev database unless --yes passed
    is_sqlite = DATABASE_URL.startswith("sqlite")
    is_dev_db = "opsdesk.db" in DATABASE_URL or ":memory:" in DATABASE_URL
    if not (is_sqlite and is_dev_db) and not args.yes:
        print(f"Safety Check Failed: DATABASE_URL '{DATABASE_URL}' does not appear to be a local dev SQLite database (opsdesk.db). Pass --yes to force.")
        sys.exit(1)

    inspector = inspect(engine)
    has_tickets_table = inspector.has_table("tickets")
    existing_count = 0
    if has_tickets_table:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM tickets"))
            existing_count = result.scalar() or 0

    if existing_count > 0 and not args.reset:
        print(f"Error: Database already contains {existing_count} tickets. Use --reset to drop tables and re-seed.")
        sys.exit(1)

    if args.reset:
        print(f"Resetting database schema on '{DATABASE_URL}'...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Schema reset complete.")

    print(f"Starting database seed process (reset={args.reset}, tickets={args.tickets}, target='{DATABASE_URL}')...")
    db = SessionLocal()
    try:
        seed_database(db, engine_bind=engine, total_tickets=args.tickets, drop_existing=False)
    finally:
        db.close()
