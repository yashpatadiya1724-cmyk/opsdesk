# OpsDesk Production Hardening Roadmap

This roadmap outlines the engineering initiatives required to transition OpsDesk from the hackathon demonstration architecture to an enterprise-grade production environment.

---

## 1. Authentication & Identity Management

- **Current State:** Demo auth via client-supplied `X-User-Id` header (matches demo specification in original PDF p6).
- **Target Architecture:**
  - Standard OAuth 2.0 / OpenID Connect (OIDC) or signed JWT bearer tokens (`Authorization: Bearer <token>`).
  - Integration with enterprise IdP (e.g., Okta, Google Workspace, Azure AD).
  - RBAC roles stored in cryptographically signed token claims (`roles: ["Agent", "Lead"]`).
  - Service-to-service mTLS or signed HMAC headers for webhook ingestion from travel booking engines (TBOH).

---

## 2. Database & Data Tier Evolution

- **Current State (Milestone 4 Hardened & Production Transition in Progress):**
  - SQLite with WAL mode (`PRAGMA journal_mode=WAL`), `PRAGMA busy_timeout=5000`, and `PRAGMA synchronous=NORMAL` supported for zero-configuration local development.
  - Composite indexes added (`ix_tickets_status_assigned`, `ix_tickets_assigned_status`, `ix_tickets_agency_status`, `ix_tickets_intent`).
  - Atomic ticket claim and optimistic concurrency version checking (`Ticket.version`) returning HTTP 409 Conflict.
  - Request deduplication cache via `IdempotencyRecord` table and `Idempotency-Key` header.
  - **Alembic Baseline Revision Created:** `alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, and baseline revision `0001_baseline_schema.py` tracking all 12 operational tables and indexes.
  - **PostgreSQL Dialect & Connection Pooling:** Engine creation logic in `backend/app/database.py` dynamically configures production connection pooling (`pool_size=10, max_overflow=20, pool_pre_ping=True, pool_timeout=30`) when `DATABASE_URL` starts with `postgresql` or `postgresql+psycopg`, stripping SQLite-specific connect args.
  - **Container & CI Pipeline Readiness:** `docker-compose.yml` updated with an optional PostgreSQL 16 Alpine container, and `.github/workflows/ci.yml` enhanced with a containerized PostgreSQL test job running the backend test suite under live PostgreSQL.
  - Fallback schema migration (`ensure_schema_migrations`) hardened with structured logging (`opsdesk.database`) and explicit exception re-raising.
- **Target Architecture (Next Steps):**
  - Managed PostgreSQL 16+ (AWS Aurora / Cloud SQL) with connection pooling (PgBouncer).
  - PostgreSQL row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) for multi-worker Tier-1 routing.
  - Schema migrations executed via **Alembic** (`alembic upgrade head`) automatically on container startup or CD release pipeline.
  - Read-replicas for high-volume read queries (e.g. queue dashboard and analytics aggregations).
  - Enforcement of data retention lifecycle policies (see [DATA_RETENTION.md](DATA_RETENTION.md)).

---

## 3. Realtime Event Dispatching (SSE Sidecar)

- **Current State (Milestone 4 Hardened):**
  - Resilient frontend polling (30s interval with +/- 3s random jitter, `visibilitychange` pause when tab is hidden, exponential backoff on errors from 5s to 60s, `AbortController` cancellation, and real-time client-side SLA countdown).
  - Events recorded atomically in `events_outbox`.
- **Target Architecture (Status: Planned, not built):**
  - Standalone outbox consumer daemon reading unconsumed events from `events_outbox`.
  - Go SSE Realtime Gateway reading from `events_outbox` table using PostgreSQL Change Data Capture (`LISTEN/NOTIFY` or Debezium CDC).
  - Multiplexed SSE connections supporting 5,000+ concurrent operator dashboards with agency-scoping filters.
  - Fallback to WebSocket / Long-Polling for restrictive corporate proxies.

---

## 4. Accelerated Scoring Engine (Rust Sidecar)

- **Current State:** Python reference implementation (`services/sla_engine.py` and `services/routing_engine.py`). Tested with 5,000 records. Heavy columns deferred (`defer(Ticket.description)`) during candidate queries.
- **Target Architecture (Status: Planned, not built):**
  - Rust microservice or PyO3 compiled extension implementing `calculate_queue_score_tier2` and `effective_deadline_hours`.
  - Sub-millisecond queue scoring over 50,000+ active records (design target / not measured).
  - Validated against existing `contracts/golden_vectors.json`.

---

## 5. Rate Limiting, Resiliency & Observability

- **Current State (Milestone 4 Hardened):**
  - Next.js upgraded to 15.5.29 (patched floor: >= 15.1.4 for CVE-2025-66478 / GHSA-9qr9-h5gf-34mp) and React/React-DOM upgraded to 19.0.1 (patched floor: >= 19.0.1).
  - CSV formula injection sanitization on all exported cells (prefixing `=`, `+`, `-`, `@`, `\t`, `\r` with `'`).
  - In-process sliding-window rate limiter middleware (`RATE_LIMIT_PER_MINUTE`, default 120 req/min) returning HTTP 429 + `Retry-After: 60`.
  - CSV export concurrency limiter (`CSV_EXPORT_MAX_CONCURRENCY`, default 2) returning HTTP 503 + `Retry-After: 10`.
  - Gemini LLM call timeout ceiling (`GEMINI_TIMEOUT_SECONDS`, default 3.0s) falling back safely to deterministic regex or Unclassified.
  - Database readiness probe (`GET /ready`) checking connectivity with `SELECT 1`.
  - `X-Request-ID` correlation header injected into all HTTP responses with structured duration access logs.
  - Detailed scaling runbook and failure modes documented in [SCALING_AND_INCIDENTS.md](SCALING_AND_INCIDENTS.md).
- **Target Architecture (Status: Planned, not built):**
  - Redis-backed distributed token bucket rate limiter for multi-worker deployments.
  - OpenTelemetry distributed tracing export (Jaeger / Honeycomb).
  - Prometheus metrics exporter (`/metrics`) tracking SLA breach counts, queue depths, and export streaming durations.
  - Sentry / Datadog integration for unhandled exception alerting.
