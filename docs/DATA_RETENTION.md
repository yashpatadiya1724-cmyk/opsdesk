# Data Retention and Archival Policy (OpsDesk)

## 1. Specification Mapping (PDF MVP-6)
Source: *Zendesk-Darwin box Automation.pdf*, Page 6:
> **MVP-6 · Data access for ops**
> - Persist tickets across refreshes
> - Uncapped export / API beyond artificial 3K-row UX barrier
> - Retention / archival strategy

---

## 2. Retention Lifecycle Tiers

| Tier | Lifecycle Window | Storage Medium | Operational SLA | Accessibility |
|---|---|---|---|---|
| **Hot Storage** | Active & Open tickets, and Closed tickets <= 90 days | Primary PostgreSQL / SQLite (Indexed) | < 50ms query latency | Full interactive UI, queue routing, real-time search |
| **Warm Storage** | Closed & Resolved cases between 91 days and 365 days | Primary database (partitioned table) | < 200ms query latency | Read-only search, audit lookups, ops export |
| **Cold Archival** | Cases older than 365 days (1 year) | Compressed parquet / object storage (S3/GCS) | Minutes (batch export) | Lead ops data dumps, compliance audit retrieval |

---

## 3. Uncapped Ops Export (Streaming Strategy)
- Traditional support platforms enforce an artificial 3,000 to 5,000 row export ceiling.
- OpsDesk provides a native streaming CSV endpoint (`GET /api/export/tickets.csv`) restricted strictly to the **Lead** role.
- Architecture:
  - Backed by SQLAlchemy cursor chunking (`yield_per(500)`).
  - FastAPI `StreamingResponse` pushes bytes incrementally over HTTP.
  - Zero server memory buffering, enabling full multi-thousand record exports with predictable $O(1)$ memory consumption.

---

## 4. Archival and Compliance Assumptions
The following policies represent concrete operational assumptions adopted for OpsDesk:
- **Statutory Audit Window (Assumption):** Financial and booking disputes in B2B travel operations require case records to be retained for 7 years prior to purge, matching standard corporate financial audit standards.
- **PII Scrubbing (Assumption):** Personal Identifiable Information (traveler names, phone numbers, passport references) is automatically scrubbed from ticket bodies and side-threads 180 days after a ticket enters `Closed` status, leaving TBOH reference codes, agency IDs, audit trails, and financial themes intact.
- **Uncapped Export Performance (Assumption):** While SQLite local development handles 5,000-row streaming in under 1 second, production PostgreSQL deployments will pair the streaming endpoint with database replica pooling to prevent lock contention on write-heavy triage queues.
