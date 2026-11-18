# OpsDesk Incident Response Runbook

This runbook documents operational procedures for diagnosing and resolving production incidents in OpsDesk. Every symptom, root cause, inspection step, and remedy matches the actual implementation in the codebase.

---

## Quick Reference Incident Matrix

| Symptom | Direct Cause | What to Inspect | Remediation Steps |
| :--- | :--- | :--- | :--- |
| **HTTP 429 Too Many Requests** | Per-process rate limit exceeded (`RATE_LIMIT_PER_MINUTE`, default: 120 req/min/IP). | Response header `Retry-After: 60`, body `{"detail": "Rate limit exceeded. Try again in 60 seconds."}`. Server log: `{"event": "rate_limit_exceeded", "client_ip": ...}`. | 1. Verify frontend jitter and exponential backoff are active.<br>2. Check for polling loops without `document.hidden` pause.<br>3. Increase `RATE_LIMIT_PER_MINUTE` if legitimate traffic burst.<br>4. Note: In-memory limiter is per-process; for multi-worker scaling, configure Redis. |
| **HTTP 503 Service Unavailable (Export)** | Export concurrency guard triggered (`EXPORT_MAX_CONCURRENT = 2` in `export_tickets_csv`). | Response header `Retry-After: 5`, body `{"detail": "Too many concurrent exports. Please try again shortly."}`. Server log: `{"event": "export_capacity_exceeded"}`. | 1. Client must respect `Retry-After` header.<br>2. Avoid parallel automated script exports.<br>3. For high-volume reporting, plan asynchronous background export job or read-replica querying. |
| **HTTP 409 Conflict (Stale Write)** | Optimistic concurrency check failed (`ticket.version != payload.version`). | Response body `Conflict: Stale write. Ticket is at version X, expected Y`. | 1. Client UI must fetch latest ticket state via `GET /api/tickets/{id}`.<br>2. Re-prompt user with diff or latest assignee/status.<br>3. Submit update with refreshed version number. |
| **HTTP 409 Conflict (Idempotency Mismatch)** | Same `Idempotency-Key` re-used with different request payload. | Response body `Conflict: Idempotency-Key was already used with a different request payload.` | 1. Inspect client logic generating `Idempotency-Key`.<br>2. Ensure unique UUIDv4 is generated for every distinct ticket creation intent.<br>3. If payload changed, issue with a fresh idempotency key. |
| **Dead-Letter Queue (DLQ) Rows** | Transactional outbox event failed 5 dispatch attempts (`EventOutbox.retry_count >= 5`). | Query: `SELECT id, event_type, ticket_id, retry_count, last_error FROM events_outbox WHERE status = 'dead_letter';`<br>Worker log: `{"status": "dead_letter", "error": ...}`. | 1. Inspect `last_error` column in `events_outbox`.<br>2. Fix external destination endpoint or webhook receiver.<br>3. Replay failed event by resetting `status = 'pending', retry_count = 0` in database.<br>4. Note: `purge_delivered_retention` purges delivered rows (>30 days) but strictly preserves all DLQ rows for auditability. |
| **"database is locked"** | SQLite write lock contention exceeded `busy_timeout` (5000 ms). | Server log search: grep `"database is locked"` or `OperationalError`. | 1. Verify WAL mode is enabled: `PRAGMA journal_mode;` must return `wal`.<br>2. Verify `busy_timeout` is 5000ms: `PRAGMA busy_timeout;`.<br>3. Ensure long-running queries do not hold write transactions open.<br>4. For high-concurrency multi-agent writes, migrate to PostgreSQL (see `README.md`). |
| **Readiness / Health Failure (503)** | Database connectivity probe failed in `GET /health` (`SELECT 1`). | Response: `{"status": "degraded", "database": "error: ...", "environment": ...}`. Server log at startup. | 1. Check file permissions on SQLite database file.<br>2. Verify filesystem has free disk space.<br>3. Verify path in `DATABASE_URL` is accessible.<br>4. Restart service if process handle is blocked. |
| **Slow Request Latency** | Query or scoring bottleneck under heavy traffic. | Header `X-Request-Id` on HTTP response.<br>Server access logs: grep by `request_id` to inspect `duration_ms`. | 1. Locate request in access logs using `request_id`.<br>2. Check if triage cache was hit (`_triage_cache`, TTL 2.0s).<br>3. Verify relationship queries use `selectinload` to prevent N+1.<br>4. Ensure client applies query filters (`intent`, `priority`, `status`) to avoid unbounded full table scans. |

---

## Diagnostic Procedures

### 1. Tracing Requests by Request ID
Every request receives an `X-Request-Id` header (or passes through client-supplied `X-Request-Id`).
Structured JSON access logs include `request_id`, `path`, `status_code`, and `duration_ms`:
```bash
# Example log entry:
# {"event": "request_completed", "request_id": "c1f78e22-...", "method": "GET", "path": "/api/tickets", "status_code": 200, "duration_ms": 17.5}
```

### 2. Inspecting Outbox DLQ State
```sql
-- Check count of dead-lettered events
SELECT count(*) FROM events_outbox WHERE status = 'dead_letter';

-- Inspect specific failures
SELECT id, event_type, ticket_id, retry_count, last_error, created_at 
FROM events_outbox 
WHERE status = 'dead_letter' 
ORDER BY created_at DESC 
LIMIT 20;
```

### 3. Outbox Retention Cleanup
```bash
# Run worker single-pass with retention purge (default: 30 days)
python scripts/outbox_worker.py --once
```
Delivered events older than 30 days are purged while dead-letter and pending events remain permanently preserved.
