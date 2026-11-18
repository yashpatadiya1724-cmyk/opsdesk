import logging
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from backend.app.config import DATABASE_URL

logger = logging.getLogger("opsdesk.database")

# Environment configuration with production defaults
# Defaults: pool_size=10, max_overflow=20, pool_timeout=30 (assumption: suitable for moderate concurrent workers)
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))


def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Hardens SQLite for high concurrent reads and writes:
    - WAL (Write-Ahead Logging): Allows concurrent readers and writers without blocking readers.
    - busy_timeout=5000: Waits up to 5,000ms for locks before raising 'database is locked'.
    - synchronous=NORMAL: Safe with WAL mode, drastically reduces sync disk wait.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine_options(url: str, **kwargs) -> dict:
    """
    Resolves SQLAlchemy engine options based on database URL scheme:
    - PostgreSQL: pool_size=10, max_overflow=20, pool_pre_ping=True, pool_timeout=30.
    - SQLite: connect_args={"check_same_thread": False}, StaticPool if :memory:.
    """
    options = dict(kwargs)
    if url.startswith("postgresql"):
        options.setdefault("pool_size", DB_POOL_SIZE)
        options.setdefault("max_overflow", DB_MAX_OVERFLOW)
        options.setdefault("pool_pre_ping", True)
        options.setdefault("pool_timeout", DB_POOL_TIMEOUT)
        # Ensure SQLite-specific flags are not passed to PostgreSQL
        if "connect_args" in options and isinstance(options["connect_args"], dict):
            options["connect_args"] = {
                k: v for k, v in options["connect_args"].items() if k != "check_same_thread"
            }
    elif url.startswith("sqlite"):
        connect_args = dict(options.get("connect_args", {}))
        connect_args.setdefault("check_same_thread", False)
        options["connect_args"] = connect_args
        if ":memory:" in url:
            options.setdefault("poolclass", StaticPool)
    return options


def create_db_engine(url: str = DATABASE_URL, **kwargs):
    """
    Factory function to create a SQLAlchemy engine with dialect-specific optimizations.
    """
    engine_kwargs = get_engine_options(url, **kwargs)
    eng = create_engine(url, **engine_kwargs)
    if url.startswith("sqlite"):
        event.listen(eng, "connect", set_sqlite_pragma)
    return eng


# Backwards compatibility alias
get_engine_for_url = create_db_engine

# Global application engine
is_sqlite = DATABASE_URL.startswith("sqlite")
is_memory = ":memory:" in DATABASE_URL
engine = create_db_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema_migrations(engine_obj):
    """
    Lightweight schema migration ensuring new columns and tables exist on existing SQLite databases.
    Logs migration activities and errors with opsdesk.database logger.
    Raises on fatal errors so broken migrations do not fail silently.
    """
    from sqlalchemy import text
    from backend.app import models  # register all models on Base

    logger.info("Starting schema verification and lightweight migrations on engine: %s", engine_obj)
    try:
        models.Base.metadata.create_all(bind=engine_obj)
        logger.info("Base metadata create_all completed successfully.")
    except Exception as exc:
        logger.error("Failed to create tables via Base.metadata.create_all: %s", exc, exc_info=True)
        raise

    is_sqlite_engine = getattr(engine_obj.dialect, "name", "") == "sqlite" or str(getattr(engine_obj, "url", "")).startswith("sqlite")
    if is_sqlite_engine:
        try:
            with engine_obj.connect() as conn:
                res = conn.execute(text("PRAGMA table_info(tickets)")).fetchall()
                cols = [r[1] for r in res]
                if cols and "version" not in cols:
                    logger.info("Adding column 'version' to tickets table")
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN version INTEGER DEFAULT 1 NOT NULL"))
                    conn.commit()
                if cols and "hotel_timezone" not in cols:
                    logger.info("Adding column 'hotel_timezone' to tickets table")
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN hotel_timezone VARCHAR(64) DEFAULT 'UTC'"))
                    conn.commit()
                if cols and "effective_deadline_at" not in cols:
                    logger.info("Adding column 'effective_deadline_at' to tickets table")
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN effective_deadline_at DATETIME"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_effective_deadline_at ON tickets (effective_deadline_at)"))
                    conn.commit()
                if cols and "queue_score" not in cols:
                    logger.info("Adding column 'queue_score' to tickets table")
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN queue_score FLOAT"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_queue_score ON tickets (queue_score)"))
                    conn.commit()

                res_check = conn.execute(text("PRAGMA table_info(tickets)")).fetchall()
                updated_cols = [r[1] for r in res_check]
                if "queue_score" in updated_cols and "effective_deadline_at" in updated_cols:
                    null_rows = conn.execute(text(
                        "SELECT id, priority, check_in_date, lcd_date, intent, agency_id FROM tickets WHERE queue_score IS NULL"
                    )).fetchall()
                    if null_rows:
                        logger.info("Backfilling queue_score and effective_deadline_at for %d tickets", len(null_rows))
                        agencies_rows = conn.execute(text("SELECT id, tier FROM agencies")).fetchall()
                        agency_tier_map = {row[0]: row[1] for row in agencies_rows}
                        from datetime import datetime, timezone
                        from backend.services.routing_engine import calculate_queue_score_tier2
                        from backend.services.sla_engine import to_utc_aware
                        now = datetime.now(timezone.utc)
                        for t_id, prio, cid_raw, lcd_raw, intent_val, agy_id in null_rows:
                            cid = datetime.fromisoformat(cid_raw) if isinstance(cid_raw, str) else cid_raw
                            lcd = datetime.fromisoformat(lcd_raw) if isinstance(lcd_raw, str) and lcd_raw else (lcd_raw if lcd_raw else None)
                            cid_aware = to_utc_aware(cid)
                            lcd_aware = to_utc_aware(lcd) if lcd else None
                            cancellation_intents = {"Refund Request", "Cancellation Inconvenience", "Unclassified", None}
                            if intent_val in cancellation_intents and lcd_aware is not None:
                                eff_deadline = min(cid_aware, lcd_aware) if cid_aware else lcd_aware
                            else:
                                eff_deadline = cid_aware

                            agy_tier = agency_tier_map.get(agy_id, "standard")
                            score = calculate_queue_score_tier2(
                                priority=prio,
                                check_in_date=cid,
                                agency_tier=agy_tier,
                                lcd_date=lcd,
                                intent=intent_val,
                                now=now
                            )
                            deadline_val = eff_deadline.replace(tzinfo=None) if eff_deadline else None
                            conn.execute(
                                text("UPDATE tickets SET effective_deadline_at = :deadline, queue_score = :score WHERE id = :tid"),
                                {"deadline": deadline_val, "score": score, "tid": t_id}
                            )
                        conn.commit()
                        logger.info("Backfill complete.")

                res_agencies = conn.execute(text("PRAGMA table_info(agencies)")).fetchall()
                cols_agencies = [r[1] for r in res_agencies]
                if cols_agencies and "tier" not in cols_agencies:
                    logger.info("Adding column 'tier' to agencies table")
                    conn.execute(text("ALTER TABLE agencies ADD COLUMN tier VARCHAR(32) DEFAULT 'standard'"))
                    conn.commit()

                res_users = conn.execute(text("PRAGMA table_info(users)")).fetchall()
                cols_users = [r[1] for r in res_users]
                if cols_users and "hashed_password" not in cols_users:
                    logger.info("Adding column 'hashed_password' to users table")
                    conn.execute(text("ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255)"))
                    conn.commit()

                res_idem = conn.execute(text("PRAGMA table_info(idempotency_records)")).fetchall()
                cols_idem = [r[1] for r in res_idem]
                if cols_idem and "request_hash" not in cols_idem:
                    logger.info("Adding column 'request_hash' to idempotency_records table")
                    conn.execute(text("ALTER TABLE idempotency_records ADD COLUMN request_hash VARCHAR(64)"))
                    conn.commit()

                res_outbox = conn.execute(text("PRAGMA table_info(events_outbox)")).fetchall()
                cols_outbox = [r[1] for r in res_outbox]
                if cols_outbox and "status" not in cols_outbox:
                    logger.info("Adding column 'status' to events_outbox table")
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN status VARCHAR(20) DEFAULT 'pending' NOT NULL"))
                    conn.commit()
                if cols_outbox and "retry_count" not in cols_outbox:
                    logger.info("Adding column 'retry_count' to events_outbox table")
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN retry_count INTEGER DEFAULT 0 NOT NULL"))
                    conn.commit()
                if cols_outbox and "last_error" not in cols_outbox:
                    logger.info("Adding column 'last_error' to events_outbox table")
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN last_error TEXT"))
                    conn.commit()
            logger.info("SQLite lightweight schema migration completed successfully.")
        except Exception as exc:
            logger.error("Schema migration failed on engine %s: %s", engine_obj, exc, exc_info=True)
            raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
