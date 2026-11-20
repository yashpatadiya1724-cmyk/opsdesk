import os
import sys
import shutil
import tempfile
import sqlite3
import subprocess
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import sqlite, postgresql
from backend.app.models import Ticket, Agency
from backend.services.routing_engine import get_sql_queue_score_expr
from sqlalchemy.orm import sessionmaker

def generate_triage_queries():
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    eng_sqlite = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=eng_sqlite)
    session = Session()

    score_expr_sqlite = get_sql_queue_score_expr(now=now, dialect_name='sqlite')
    q_sqlite = session.query(Ticket).filter(
        Ticket.status.in_(['New', 'Open', 'Pending', 'Escalated']),
        Ticket.assigned_to.is_(None)
    ).outerjoin(Agency, Ticket.agency_id == Agency.id).order_by(
        score_expr_sqlite.desc(),
        Ticket.effective_deadline_at.asc(),
        Ticket.id.asc()
    ).limit(50)

    compiled_sqlite = str(q_sqlite.statement.compile(dialect=sqlite.dialect(), compile_kwargs={'literal_binds': True}))

    score_expr_pg = get_sql_queue_score_expr(now=now, dialect_name='postgresql')
    q_pg = session.query(Ticket).filter(
        Ticket.status.in_(['New', 'Open', 'Pending', 'Escalated']),
        Ticket.assigned_to.is_(None)
    ).outerjoin(Agency, Ticket.agency_id == Agency.id).order_by(
        score_expr_pg.desc(),
        Ticket.effective_deadline_at.asc(),
        Ticket.id.asc()
    ).limit(50)

    compiled_pg = str(q_pg.statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))

    return compiled_sqlite, compiled_pg

def run_sqlite_explain(compiled_sqlite):
    temp_db = os.path.join(tempfile.gettempdir(), 'explain_temp.db')
    if os.path.exists(temp_db):
        os.remove(temp_db)
    shutil.copyfile('opsdesk.db', temp_db)

    temp_db_clean = temp_db.replace('\\', '/')
    url = f'sqlite:///{temp_db_clean}'
    python_exe = sys.executable
    subprocess.run([python_exe, 'scripts/upgrade_legacy_db.py', '--db-url', url], check=True, capture_output=True)

    con = sqlite3.connect(temp_db)
    cur = con.cursor()
    cur.execute(f'EXPLAIN QUERY PLAN {compiled_sqlite}')
    rows = cur.fetchall()
    con.close()
    if os.path.exists(temp_db):
        os.remove(temp_db)
    return rows

def run_pg_explain(compiled_pg, db_url=None):
    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set for PostgreSQL EXPLAIN")
        return
    eng = create_engine(db_url)
    with eng.connect() as conn:
        res = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled_pg}"))
        print("\n=== POSTGRESQL EXPLAIN (ANALYZE, BUFFERS) ===")
        for r in res.fetchall():
            print(r[0])

if __name__ == '__main__':
    sql_lite, sql_pg = generate_triage_queries()
    print("=== SQLITE COMPILED SQL ===")
    print(sql_lite)
    print("\n=== POSTGRESQL COMPILED SQL ===")
    print(sql_pg)

    if "--pg-only" not in sys.argv:
        print("\n=== SQLITE EXPLAIN QUERY PLAN ===")
        plan = run_sqlite_explain(sql_lite)
        for row in plan:
            print(row)

    if "--pg-explain" in sys.argv or "--pg-only" in sys.argv:
        run_pg_explain(sql_pg)
