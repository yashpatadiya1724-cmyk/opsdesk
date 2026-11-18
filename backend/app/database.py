import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from backend.app.config import DATABASE_URL

# Environment configuration with production defaults
# Defaults: pool_size=10, max_overflow=20, pool_timeout=30 (assumption: suitable for moderate concurrent workers)
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

is_sqlite = DATABASE_URL.startswith("sqlite")
is_memory = ":memory:" in DATABASE_URL

connect_args = {"check_same_thread": False} if is_sqlite else {}
engine_kwargs = {"connect_args": connect_args}

if is_sqlite and is_memory:
    engine_kwargs["poolclass"] = StaticPool
else:
    engine_kwargs["pool_size"] = DB_POOL_SIZE
    engine_kwargs["max_overflow"] = DB_MAX_OVERFLOW
    engine_kwargs["pool_timeout"] = DB_POOL_TIMEOUT

engine = create_engine(DATABASE_URL, **engine_kwargs)

if is_sqlite:
    @event.listens_for(engine, "connect")
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

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def ensure_schema_migrations(engine_obj):
    """
    Lightweight schema migration ensuring new columns and tables exist on existing SQLite databases.
    """
    from sqlalchemy import text
    from backend.app import models  # register all models on Base
    models.Base.metadata.create_all(bind=engine_obj)
    if is_sqlite:
        try:
            with engine_obj.connect() as conn:
                res = conn.execute(text("PRAGMA table_info(tickets)")).fetchall()
                cols = [r[1] for r in res]
                if cols and "version" not in cols:
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN version INTEGER DEFAULT 1 NOT NULL"))
                    conn.commit()
                if cols and "hotel_timezone" not in cols:
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN hotel_timezone VARCHAR(64) DEFAULT 'UTC'"))
                    conn.commit()

                res_agencies = conn.execute(text("PRAGMA table_info(agencies)")).fetchall()
                cols_agencies = [r[1] for r in res_agencies]
                if cols_agencies and "tier" not in cols_agencies:
                    conn.execute(text("ALTER TABLE agencies ADD COLUMN tier VARCHAR(32) DEFAULT 'standard'"))
                    conn.commit()

                res_users = conn.execute(text("PRAGMA table_info(users)")).fetchall()
                cols_users = [r[1] for r in res_users]
                if cols_users and "hashed_password" not in cols_users:
                    conn.execute(text("ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255)"))
                    conn.commit()

                res_idem = conn.execute(text("PRAGMA table_info(idempotency_records)")).fetchall()
                cols_idem = [r[1] for r in res_idem]
                if cols_idem and "request_hash" not in cols_idem:
                    conn.execute(text("ALTER TABLE idempotency_records ADD COLUMN request_hash VARCHAR(64)"))
                    conn.commit()

                res_outbox = conn.execute(text("PRAGMA table_info(events_outbox)")).fetchall()
                cols_outbox = [r[1] for r in res_outbox]
                if cols_outbox and "status" not in cols_outbox:
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN status VARCHAR(20) DEFAULT 'pending' NOT NULL"))
                    conn.commit()
                if cols_outbox and "retry_count" not in cols_outbox:
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN retry_count INTEGER DEFAULT 0 NOT NULL"))
                    conn.commit()
                if cols_outbox and "last_error" not in cols_outbox:
                    conn.execute(text("ALTER TABLE events_outbox ADD COLUMN last_error TEXT"))
                    conn.commit()
        except Exception:
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
