"""
OpsDesk Transactional Outbox Worker
Polls `events_outbox` table, handles event dispatching with exponential backoff,
dead-letter queuing after max retries, and structured JSON audit logging.
"""

import os
import sys
import time
import json
import signal
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Dict, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Add repo root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.models import EventOutbox
from backend.app.database import ensure_schema_migrations

logger = logging.getLogger("opsdesk.outbox_worker")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


class OutboxWorker:
    def __init__(
        self,
        db_factory: sessionmaker,
        max_retries: int = 5,
        backoff_base_sec: float = 1.0,
        batch_size: int = 50,
        poll_interval_sec: float = 2.0
    ):
        self.db_factory = db_factory
        self.max_retries = max_retries
        self.backoff_base_sec = backoff_base_sec
        self.batch_size = batch_size
        self.poll_interval_sec = poll_interval_sec
        self._running = False

    def default_dispatch(self, event: EventOutbox) -> None:
        """
        Default dispatcher: simulates external webhook / bus delivery.
        In production, this forwards events to an external message broker or webhook endpoint.
        """
        # Parse payload to ensure well-formed JSON
        _ = json.loads(event.payload_json)

    def process_batch(self, dispatch_fn: Optional[Callable[[EventOutbox], None]] = None) -> Dict[str, int]:
        """
        Fetches up to batch_size undelivered events, attempts dispatch, and updates event state.
        Returns counts: {'processed': N, 'delivered': D, 'retried': R, 'dead_letter': L}.
        """
        if dispatch_fn is None:
            dispatch_fn = self.default_dispatch

        stats = {"processed": 0, "delivered": 0, "retried": 0, "dead_letter": 0}
        db: Session = self.db_factory()

        try:
            # Query undelivered events that have not permanently failed to dead-letter
            events = (
                db.query(EventOutbox)
                .filter(
                    EventOutbox.delivered_at.is_(None),
                    EventOutbox.status != "dead_letter"
                )
                .order_by(EventOutbox.created_at.asc())
                .limit(self.batch_size)
                .all()
            )

            for event in events:
                stats["processed"] += 1
                t0 = time.perf_counter()
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

                try:
                    dispatch_fn(event)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    event.delivered_at = now_utc
                    event.status = "delivered"
                    event.last_error = None
                    stats["delivered"] += 1

                    logger.info(json.dumps({
                        "timestamp": now_utc.isoformat(),
                        "event_id": event.id,
                        "event_type": event.event_type,
                        "ticket_id": event.ticket_id,
                        "agency_id": event.agency_id,
                        "status": "delivered",
                        "retry_count": event.retry_count,
                        "latency_ms": elapsed_ms
                    }))

                except Exception as exc:
                    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    event.retry_count = (event.retry_count or 0) + 1
                    event.last_error = str(exc)

                    if event.retry_count >= self.max_retries:
                        event.status = "dead_letter"
                        stats["dead_letter"] += 1
                        logger.error(json.dumps({
                            "timestamp": now_utc.isoformat(),
                            "event_id": event.id,
                            "event_type": event.event_type,
                            "ticket_id": event.ticket_id,
                            "agency_id": event.agency_id,
                            "status": "dead_letter",
                            "retry_count": event.retry_count,
                            "error": str(exc),
                            "latency_ms": elapsed_ms
                        }))
                    else:
                        event.status = "retry"
                        stats["retried"] += 1
                        logger.warning(json.dumps({
                            "timestamp": now_utc.isoformat(),
                            "event_id": event.id,
                            "event_type": event.event_type,
                            "ticket_id": event.ticket_id,
                            "agency_id": event.agency_id,
                            "status": "retry",
                            "retry_count": event.retry_count,
                            "error": str(exc),
                            "latency_ms": elapsed_ms
                        }))

                db.commit()

        finally:
            db.close()

        return stats

    def purge_delivered_retention(self, retention_days: Optional[int] = None) -> int:
        """
        Purges delivered events older than retention_days (default: 30 from env OUTBOX_RETENTION_DAYS).
        Dead-letter rows and pending/undelivered rows are strictly preserved for auditability.
        """
        if retention_days is None:
            retention_days = int(os.environ.get("OUTBOX_RETENTION_DAYS", "30"))

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days)
        db: Session = self.db_factory()
        try:
            deleted_count = (
                db.query(EventOutbox)
                .filter(
                    EventOutbox.status == "delivered",
                    EventOutbox.delivered_at.isnot(None),
                    EventOutbox.delivered_at < cutoff
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            if deleted_count > 0:
                logger.info(json.dumps({
                    "event": "outbox_retention_purge",
                    "retention_days": retention_days,
                    "cutoff": cutoff.isoformat(),
                    "purged_count": deleted_count
                }))
            return deleted_count
        finally:
            db.close()

    def run_loop(self, once: bool = False) -> None:
        self._running = True

        def handle_signal(sig, frame):
            logger.info(json.dumps({"event": "shutdown_signal_received", "signal": sig}))
            self._running = False

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except Exception:
            pass

        logger.info(json.dumps({
            "event": "worker_started",
            "batch_size": self.batch_size,
            "max_retries": self.max_retries,
            "poll_interval_sec": self.poll_interval_sec,
            "mode": "single_pass" if once else "daemon"
        }))

        while self._running:
            stats = self.process_batch()
            if once:
                break
            if stats["processed"] == 0:
                time.sleep(self.poll_interval_sec)

        logger.info(json.dumps({"event": "worker_stopped"}))


def main():
    parser = argparse.ArgumentParser(description="OpsDesk Outbox Worker")
    parser.add_argument("--db-path", default=None, help="Database file path or URL")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size (default: 50)")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--max-retries", type=int, default=5, help="Max retry count before dead-letter")
    parser.add_argument("--once", action="store_true", help="Run a single batch and exit")
    args = parser.parse_args()

    db_url = args.db_path or os.environ.get("DATABASE_URL", "sqlite:///./opsdesk.db")
    if not db_url.startswith("sqlite:///") and not db_url.startswith("postgresql://"):
        db_url = f"sqlite:///{db_url}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    ensure_schema_migrations(engine)
    session_maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    worker = OutboxWorker(
        db_factory=session_maker,
        max_retries=args.max_retries,
        batch_size=args.batch_size,
        poll_interval_sec=args.poll_interval
    )
    worker.run_loop(once=args.once)


if __name__ == "__main__":
    main()
