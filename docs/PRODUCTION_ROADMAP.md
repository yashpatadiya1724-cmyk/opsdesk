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

- **Current State:** Local SQLite (`opsdesk.db`) with manual table initialization and `seed_data.py`.
- **Target Architecture:**
  - Managed PostgreSQL 16+ (AWS Aurora / Cloud SQL) with connection pooling (PgBouncer).
  - Schema migrations managed via **Alembic** (`alembic upgrade head`) integrated into CI/CD deployment pipelines.
  - Read-replicas for high-volume read queries (e.g. queue dashboard and analytics aggregations).
  - Enforcement of data retention lifecycle policies (see [DATA_RETENTION.md](DATA_RETENTION.md)).

---

## 3. Realtime Event Dispatching (SSE Sidecar)

- **Current State:** SWR / HTTP Polling (15-second interval) from frontend; events recorded in `events_outbox`.
- **Target Architecture (Status: Planned, not built):**
  - Go SSE Realtime Gateway reading from `events_outbox` table using PostgreSQL Change Data Capture (`LISTEN/NOTIFY` or Debezium CDC).
  - Multiplexed SSE connections supporting 5,000+ concurrent operator dashboards with agency-scoping filters.
  - Fallback to WebSocket / Long-Polling for restrictive corporate proxies.

---

## 4. Accelerated Scoring Engine (Rust Sidecar)

- **Current State:** Python reference implementation (`services/sla_engine.py` and `services/routing_engine.py`). Tested with 5,000 records.
- **Target Architecture (Status: Planned, not built):**
  - Rust microservice or PyO3 compiled extension implementing `calculate_queue_score_tier2` and `effective_deadline_hours`.
  - Sub-millisecond queue scoring over 50,000+ active records.
  - Validated against existing `contracts/golden_vectors.json`.

---

## 5. Rate Limiting, Resiliency & Observability

- **Rate Limiting:** Redis-backed token bucket algorithm (e.g. 100 req/min for Requesters, 500 req/min for Agents).
- **Observability:**
  - Structured JSON logging with OpenTelemetry tracing headers.
  - Prometheus metrics exporter (`/metrics`) tracking SLA breach counts, queue depths, and export streaming durations.
  - Sentry / Datadog integration for unhandled exception alerting.
