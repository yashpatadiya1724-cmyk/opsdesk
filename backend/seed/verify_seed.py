import sqlite3
from datetime import datetime
from backend.services.sla_engine import evaluate_travel_sla

def run_checks(db_path: str = "opsdesk.db"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("=== 1. TOTAL TICKETS COUNT ===")
    c.execute("SELECT COUNT(*) FROM tickets")
    total = c.fetchone()[0]
    print(f"Total: {total}")

    print("\n=== 2. COUNT BY STATUS ===")
    c.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status ORDER BY COUNT(*) DESC")
    for status, count in c.fetchall():
        print(f"{status}: {count}")

    print("\n=== 3. OPEN TICKETS WITH PAST CHECK-IN (MUST BE 0) ===")
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    query = """
    SELECT COUNT(*) FROM tickets 
    WHERE status IN ('New', 'Open', 'Pending', 'Escalated') 
      AND check_in_date < ?
    """
    c.execute(query, (now_iso,))
    past_active = c.fetchone()[0]
    print(f"Past check-in active tickets count: {past_active}")

    print("\n=== 4. SLA STATUS BREAKDOWN (ALL 5,000 TICKETS) ===")
    c.execute("SELECT status, check_in_date, lcd_date, priority, intent FROM tickets")
    rows = c.fetchall()

    sla_counts = {"STOPPED": 0, "BREACHED": 0, "AT_RISK": 0, "NORMAL": 0}
    now = datetime.utcnow()

    for status, cid_str, lcd_str, prio, intent in rows:
        cid = datetime.fromisoformat(cid_str)
        lcd = datetime.fromisoformat(lcd_str) if lcd_str else None
        res = evaluate_travel_sla(status=status, check_in_date=cid, lcd_date=lcd, priority=prio, intent=intent, now=now)
        sla_counts[res["status"]] += 1

    for st, cnt in sla_counts.items():
        print(f"{st}: {cnt}")

    print("\n=== 5. ESCALATED TICKETS ASSIGNEE BREAKDOWN ===")
    c.execute("""
    SELECT assigned_to, COUNT(*) 
    FROM tickets 
    WHERE status = 'Escalated' 
    GROUP BY assigned_to
    """)
    for assignee, cnt in c.fetchall():
        print(f"Assigned to {assignee}: {cnt}")

    print("\n=== 6. NON-ESCALATED ASSIGNED AGENTS BREAKDOWN ===")
    c.execute("""
    SELECT assigned_to, COUNT(*) 
    FROM tickets 
    WHERE status != 'Escalated' AND assigned_to IS NOT NULL 
    GROUP BY assigned_to
    """)
    for assignee, cnt in c.fetchall():
        print(f"Assigned to {assignee}: {cnt}")

    print("\n=== 7. JOURNEY FIXTURES (TCK-1001, 1002, 1004, 1005, 1006, 1007) ===")
    c.execute("""
    SELECT id, status, priority, assigned_to, check_in_date 
    FROM tickets 
    WHERE id IN ('TCK-1001', 'TCK-1002', 'TCK-1004', 'TCK-1005', 'TCK-1006', 'TCK-1007')
    ORDER BY id
    """)
    for row in c.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    run_checks()
