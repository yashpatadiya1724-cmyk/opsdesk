"""Upgrade legacy OpsDesk database schema to latest hardened version using Alembic.

Usage:
    python scripts/upgrade_legacy_db.py [--db-url sqlite:///path/to/db.db]
"""
import argparse
import os
import sys
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.app.config import DATABASE_URL


def upgrade_legacy_db(db_url: str) -> None:
    print(f"[*] Upgrading legacy database at: {db_url}")
    ini_path = os.path.join(REPO_ROOT, "alembic.ini")
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    engine = create_engine(db_url)
    with engine.connect() as conn:
        from sqlalchemy import inspect
        insp = inspect(conn)
        has_alembic = insp.has_table('alembic_version')

        if not has_alembic:
            print("[*] Stamping baseline 0001_baseline_schema on legacy database...")
            command.stamp(alembic_cfg, "0001_baseline_schema")
        else:
            current_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"[*] Current revision: {current_rev}")
            if current_rev == "0002_timezone_aware_and_queue_score":
                print("[*] Migrating legacy revision id '0002_timezone_aware_and_queue_score' to '0002_tz_aware_priority_weight'...")
                conn.execute(
                    text("UPDATE alembic_version SET version_num='0002_tz_aware_priority_weight' WHERE version_num='0002_timezone_aware_and_queue_score'")
                )
                conn.commit()

    print("[*] Running alembic upgrade head...")
    command.upgrade(alembic_cfg, "head")

    # Run lightweight schema safety check for any legacy columns
    from backend.app.database import ensure_schema_migrations
    ensure_schema_migrations(engine)

    # Verification
    with engine.connect() as conn:
        user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        ticket_count = conn.execute(text("SELECT COUNT(*) FROM tickets")).scalar()
        urgent_weight = conn.execute(
            text("SELECT priority_weight FROM tickets WHERE priority='Urgent' LIMIT 1")
        ).scalar()
        high_weight = conn.execute(
            text("SELECT priority_weight FROM tickets WHERE priority='High' LIMIT 1")
        ).scalar()
        null_deadlines = conn.execute(
            text("SELECT COUNT(*) FROM tickets WHERE effective_deadline_at IS NULL")
        ).scalar()

        print(f"[+] Upgraded successfully:")
        print(f"    - Users: {user_count}")
        print(f"    - Tickets: {ticket_count}")
        print(f"    - Urgent priority_weight: {urgent_weight}")
        print(f"    - High priority_weight: {high_weight}")
        print(f"    - Tickets with NULL effective_deadline_at: {null_deadlines}")

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upgrade legacy database")
    parser.add_argument("--db-url", default=None, help="Database URL to upgrade")
    args = parser.parse_args()

    target_url = args.db_url or os.getenv("DATABASE_URL", DATABASE_URL)
    upgrade_legacy_db(target_url)
