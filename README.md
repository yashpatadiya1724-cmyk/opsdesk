# OpsDesk: B2B Travel Operations Case Management Platform

[![CI](https://github.com/yashpatadiya1724-cmyk/opsdesk/actions/workflows/ci.yml/badge.svg)](https://github.com/yashpatadiya1724-cmyk/opsdesk/actions/workflows/ci.yml)

**OpsDesk** is a deterministic B2B travel operations dispatcher built to replace fragmented helpdesks with context-linked operational cases aligned with physical travel reality.

Designed specifically for travel consolidators, online travel agencies (OTAs), and corporate travel desks managing bookings, supplier confirmations, and emergency traveler disruptions.

---

## 🌟 Core Value Propositions

- **First-Class TBOH Linkage:** Instantly correlates past contacts sharing the same TBO Booking Reference (`TBOH_ID`) without requiring manual lookups or external third-party add-ons.
- **Intent-Aware LCD SLA Engine:** Dynamically calculates countdowns based on guest check-in proximity and Last Cancellation Date (LCD). Distinguishes cancellation-sensitive deadlines from on-the-ground check-in emergencies.
- **Deterministic 2-Tier Routing Engine:** 
  - **Tier 1 (Emergency Bypass):** Departures or effective deadlines within 4 hours automatically trigger Tier-1 Emergency Bypass, forcing priority to `Urgent` and status to `Escalated`, jumping to Queue Rank #1.
  - **Tier 2 (Continuous Scoring):** Continuous multi-factor dynamic queue scoring factoring base priority (`Urgent`: 1000, `High`: 500, `Medium`: 200, `Low`: 50), deadline urgency modifiers (<=2h: +2000, <=6h: +800, <=24h: +300), and agency tier multipliers (Platinum: 1.3x, Gold: 1.15x, Standard: 1.0x).
- **Hotel Timezone & UTC Normalization:** Native `hotel_timezone` support on tickets (default `"UTC"`). Local hotel check-in and cancellation timestamps are localized to property timezones (e.g. `Asia/Dubai`, `Asia/Kolkata`) and normalized to timezone-aware UTC for drift-free SLA countdowns and queue ranking.
- **Transfer-Proof Supplier Threads:** Decouples supplier conversation recipients from internal ticket assignees, guaranteeing that external communications remain preserved across agent transfers.
- **Streaming Ops Data Path:** Eliminates artificial 3,000-row export barriers via direct SQL database cursor streaming (`yield_per(500)`) with cursor pagination (`cursor`, `limit`, `X-Next-Cursor` header) and formula injection sanitization. Benchmarked at **5,000 rows in ~1.32s**.
- **Global TBOH & Ticket Search:** Instant search by `TBOH_ID`, Ticket ID, or `title` combined with Priority and Status multi-attribute filtering (omits wildcard matching on large `description` bodies to prevent full table scans).
- **Quick Action Command Palette (`Ctrl+K`):** Global operational keyboard shortcuts for immediate case jumping, role switching, and filtering.
- **Modern In-App Toast System:** Lightweight, non-blocking notification engine replacing browser `alert()` modals.
- **Operations Terminal CLI:** Interactive developer and ops terminal inspector (`scripts/opsdesk_cli.py`) for live triage and case 360 diagnostics.
- **Modern Next.js 15 Frontend:** SaaS light theme operations console featuring a resilient 30s jittered polling Queue, Thread Viewer, Role Switcher with demo auth warning, AI Intent Auto-Suggest, and Operational Insights.

---

## 📋 MVP Implementation Status (Mapped to PDF Pages 5–6)

This matrix strictly maps against the requirements specified in the project specification (*Zendesk-Darwin box Automation.pdf*, Pages 5–6):

| MVP # & Name | Source (PDF Page) | Specification & Core Capabilities | Backend Status | UI Status | Implementation Details |
|---|---|---|:---:|:---:|---|
| **MVP-1 · Context-rich tickets** | Page 5 | • Create tickets with title, description, agency identity, TBOH, priority, category/intent, travel fields (check-in/LCD)<br>• Link tickets by TBOH, agency, and/or intent without third-party apps<br>• Intent taxonomy: manual select + rule auto-suggest / lightweight ML<br>• Status flow: New → Open → Pending → Escalated → Resolved → Closed<br>• Activity timeline: status, assignment, links, escalations | **Implemented** | **Implemented** | **Backend:** `POST /api/tickets`, `GET /api/tickets/{id}`, rule classifier, atomic audit logs.<br>**UI:** Create Ticket Modal with Auto-Suggest Intent, Ticket Detail Activity Timeline. |
| **MVP-2 · Routing & ownership** | Page 5 | • Assign / reassign / unassign with clear ownership<br>• Beyond FIFO/LIFO: region/country desk match + time window + priority score + availability<br>• Views: triage (unassigned), my queue, by region, by intent, linked-case view<br>• Audit reason explaining why ticket was routed | **Implemented** | **Implemented** | **Backend:** Tier-1 emergency bypass (4 hours, Urgent, Escalated) + Tier-2 dynamic queue scoring (Platinum 1.3x, Gold 1.15x, Standard 1.0x) in `backend/services/routing_engine.py`.<br>**UI:** Queue page with Triage, My Queue, By Region, By Intent, Linked tabs, and routing reason tooltip. |
| **MVP-3 · Side conversations** | Page 5 | • Side-conversation threads with explicit recipient lists (decoupled from assignee)<br>• Recipients stay correct and preserved after agent transfer<br>• Distinguish internal notes (`InternalNote`) vs external replies (`PublicReply`) | **Implemented** | **Implemented** | **Backend:** `/side-threads` endpoints, message types, and recipient preservation on transfer.<br>**UI:** Thread toggle (Public Reply vs Internal Note) + Supplier side-thread composer. |
| **MVP-4 · Travel-aware SLA & escalation** | Page 6 | • Dynamic SLA countdown using priority + check-in / LCD proximity<br>• At-risk / breached indicators on queue<br>• Escalate to Escalation Manager as a first-class action (reassigns to manager queue, logs on timeline) | **Implemented** | **Implemented** | **Backend:** `sla_engine.py` (effective deadline helper with hotel timezone UTC normalization) + `POST /api/tickets/{id}/escalate`.<br>**UI:** Visual SLA badges (`NORMAL`, `AT_RISK`, `BREACHED`) with 30s live countdown polling & Escalate action. |
| **MVP-5 · Feedback / insight loop** | Page 6 | • Tag or extract themes (refund delay, supplier lag, cancellation penalty)<br>• Insights view: top themes this week + sample tickets<br>• Optional: suggested link to product / bug<br>• Stretch: AI assist that uses linked history | **Implemented** | **Implemented** | **Backend:** `GET /api/insights/themes` + `POST /api/tickets/{id}/link-suggestion`.<br>**UI:** `/insights` analytics dashboard showing recurring themes, percentage bars, and sample ticket links. |
| **MVP-6 · Data access for ops** | Page 6 | • Persist tickets across refreshes<br>• Streaming export / API beyond artificial 3K-row UX barrier<br>• Retention / archival strategy | **Implemented** | **Implemented** | **Backend:** Memory-safe `yield_per(500)` streaming generator (`GET /api/export/tickets.csv`) with cursor pagination (`cursor`, `limit`, `X-Next-Cursor` header), tested 5,000 rows in ~1.32s; [`docs/DATA_RETENTION.md`](docs/DATA_RETENTION.md).<br>**UI:** "Export CSV (MVP-6)" streaming download button. |
| **MVP-7 · Roles & access** | Page 6 | • Requester (agency): own tickets only (internal notes, queue scores, and other agencies' data hidden)<br>• Agent: organization queues<br>• Escalation Manager: escalation queue + managerial actions<br>• Lead: governance & queue health views<br>• Demo-only auth: identity is client-supplied, not secure (PDF p6 allows demo auth) | **Implemented** | **Implemented** | **Backend:** RBAC guards with 401/403 responses and internal field stripping. Dual authentication support: `AUTH_MODE=demo` (X-User-Id header) and `AUTH_MODE=jwt` (Bearer token, bcrypt hashing). Production startup refusal (`APP_ENV=production` blocks `AUTH_MODE=demo` unless `ALLOW_DEMO_AUTH=true`).<br>**UI:** Top navigation Role Switcher with visible Demo-Auth banner and route guards. |

---

## ⚡ Quickstart Guide

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** (tested on Node v24)
- **SQLite3** (included with standard Python)

### 1. Installation & Dependencies
Install dependencies from `requirements.txt` or the fully pinned `requirements.lock` generated via `pip freeze`:
```powershell
# Core dependencies
pip install -r requirements.txt

# Or from pinned lockfile
pip install -r requirements.lock
```

### 2. Database Setup & Seeding
```powershell
# Reset and calibrate dev database with 5,000 tickets
python -m backend.seed.seed_data --reset
```
*Seeds the development database (`opsdesk.db`) with 5,000 realistic operations tickets, calibrating Journey fixtures `TCK-1001` through `TCK-1008` relative to wall-clock time.*

#### Database Migrations (Alembic)
OpsDesk tracks schema migrations using Alembic. For production PostgreSQL deployments or explicit schema upgrades:
```powershell
# Run all pending migrations up to latest revision
alembic upgrade head

# Rollback one migration revision
alembic downgrade -1

# Generate new migration revision after modifying models
alembic revision --autogenerate -m "describe_change"
```

#### Upgrading Legacy (Pre-Hardening) Databases
Existing pre-hardening databases (merge-base `7d39b66`) can be upgraded cleanly using the migration script:
```powershell
python scripts/upgrade_legacy_db.py --db-url sqlite:///path/to/legacy.db
```
Or manually using Alembic CLI:
```powershell
alembic stamp 0001_baseline_schema
alembic upgrade head
```
This backfills `priority_weight` from `priority` (Urgent: 1000, High: 500, Medium: 200, Low: 50), backfills `effective_deadline_at` from `check_in_date`, defaults `hotel_timezone` to UTC, and adds `hashed_password` to `users`.

*Note on Stamped Dev Databases:* If a database was previously stamped with the deprecated 35-character revision identifier, fix it by executing `UPDATE alembic_version SET version_num='0002_tz_aware_priority_weight' WHERE version_num='0002_timezone_aware_and_queue_score';` (which is also handled automatically when running `scripts/upgrade_legacy_db.py`).

*Note for `AUTH_MODE=jwt` on Upgraded Databases:* Users in pre-hardening databases lack password hashes. Before logging in via JWT, administrators must set passwords for existing accounts using `python -m backend.app.manage set-password --email <email>`.

*Automated Verification:* The complete unattended legacy database upgrade from merge-base `7d39b66`, schema PRAGMA inspection, TestClient API calls, password management, and JWT token authentication are verified via `python scripts/verify_upgrade.py` (transcript recorded at [`docs/verification/upgrade_transcript.txt`](docs/verification/upgrade_transcript.txt)).

### 3. Run Backend API
```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive API Documentation: `http://127.0.0.1:8000/docs`

#### Authentication Configuration
OpsDesk supports two operational authentication modes configured via environment variables:
- **`AUTH_MODE=demo` (Default in development):** Identity is supplied via the `X-User-Id` request header (e.g. `USR-AGENT-1`), enabling instantaneous persona switching for hackathon judges and evaluators without login friction.
- **`AUTH_MODE=jwt`:** Production-grade authentication requiring `Authorization: Bearer <token>`. Issue tokens via `POST /api/auth/login` using email and bcrypt-hashed passwords (configurable work factor via `BCRYPT_ROUNDS`).
- **Production Startup Refusal:** If `APP_ENV=production` and `AUTH_MODE=demo`, the backend server refuses to start with a `RuntimeError` unless explicitly permitted via `ALLOW_DEMO_AUTH=true`. In `AUTH_MODE=jwt`, startup requires an explicit non-default `JWT_SECRET` (>= 32 chars) and an allowed algorithm (`HS256`, `HS384`, `HS512`).

#### Registered API Endpoints (19 Total)

| Method | Path | Function / Responsibility | Access Scope |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Liveness health probe | Public |
| `GET` | `/ready` | Readiness database connectivity probe (`SELECT 1`) | Public |
| `POST` | `/api/auth/login` | Authenticate with email/password, returning JWT bearer access token | Public |
| `POST` | `/api/ai/suggest-intent` | AI intent fallback suggestion (Gemini Flash, 3.0s timeout) | All Authenticated |
| `GET` | `/api/tickets` | List/filter tickets with dynamic queue scoring & SLA | Agent / Lead (Scoped for Requester) |
| `POST` | `/api/tickets` | Create ticket with regex intent, SLA & idempotency key | All Authenticated |
| `GET` | `/api/tickets/{ticket_id}` | Full ticket detail, messages, side-threads & TBOH links | Agent / Lead (Scoped for Requester) |
| `POST` | `/api/tickets/{ticket_id}/assign` | Assign ticket atomically to an operations agent (409 on race) | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/unassign` | Return ticket to unassigned triage pool atomically | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/status` | Transition ticket state with version check (409 on stale) | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/escalate` | Escalate ticket to Tier-2 escalation queue with version check | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/transfer` | Transfer ticket across regional desks with version check | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/messages` | Append message (`PublicReply` or `InternalNote`) | All (`InternalNote` staff-only) |
| `GET` | `/api/tickets/{ticket_id}/side-threads` | List supplier side conversations | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/side-threads` | Open supplier side thread with decoupled recipient | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/side-threads/{side_thread_id}/messages` | Append supplier message to existing side thread | Agent / EscalationManager / Lead |
| `POST` | `/api/tickets/{ticket_id}/link-suggestion` | Confirm or reject TBOH linked case recommendation | Agent / EscalationManager / Lead |
| `GET` | `/api/insights/themes` | Aggregate top recurring operational issue themes | EscalationManager / Lead |
| `GET` | `/api/export/tickets.csv` | Stream operations tickets with cursor pagination (`cursor`, `limit`, `X-Next-Cursor` header; concurrency limited to 2) | Lead Only |

### 4. Run Next.js 15 Frontend
```powershell
cd frontend
npm install
npm run dev
```
Open Browser: `http://localhost:3000`

---

## 🧪 Test & Verification Commands

All testing suites run against isolated test databases without modifying the development database.

> **Performance Note (Windows Defender):** On Windows, real-time filesystem scanning by Windows Defender / Antivirus can significantly slow down SQLite database operations and Python test execution. For optimal test suite speed, add the repository root folder and virtual environment (`.venv`) to Windows Defender folder exclusions.
>
> By default, `pytest` runs in fast mode excluding tests marked `slow` (`pytest -m "not slow"` configured in `pytest.ini`). To execute the complete test suite including heavy concurrency and large streaming tests, run `pytest -m "slow or not slow"`.

```powershell
# 1. Backend Fast Test Suite (Default, excluding slow tests)
pytest backend/tests -q

# 1b. Backend Full Test Suite (Including slow concurrency and export tests)
pytest backend/tests -q -m "slow or not slow"

# 2. Frontend ESLint Check (0 warnings, 0 errors)
cd frontend ; npm run lint

# 3. Frontend Production Build & TypeScript Typecheck (5 pages compiled)
cd frontend ; npm run build

# 4. Frontend-Backend Contract Integration Smoke Test (9/9 checks passed)
python scripts/smoke_frontend_api.py

# 5. Dev Database Integrity Verification (Proves zero test pollution)
powershell -ExecutionPolicy Bypass -File scripts\check_dev_db_untouched.ps1
```

---

## 🧭 Monorepo Structure

```text
opsdesk/
├── backend/                  # FastAPI core application, services, and tests
│   ├── app/                  # FastAPI router, models, schemas, auth dependencies
│   ├── seed/                 # Realistic 5,000-ticket generator with Journey fixtures
│   ├── services/             # Intent classifier, routing engine, travel SLA engine
│   └── tests/                # Test suite (157 tests: 156 passed, 1 skipped)
├── contracts/                # Shared JSON Schemas, Golden Vectors, openapi.json
│   ├── golden_vectors.json   # Contract golden vectors for SLA & scoring
│   ├── openapi.json          # Exported OpenAPI 3.1 specification
│   └── sla_engine.schema.json
├── docs/                     # Architecture & Design documentation
│   ├── adr/                  # 5 Architecture Decision Records (ADR 0001 - 0005)
│   ├── ARCHITECTURE.md       # System context, component, ERD, and state machine diagrams
│   ├── DATA_RETENTION.md     # Hot/Warm/Cold archival policies
│   ├── DEMO_RUNBOOK.md       # Pre-demo checklist, Journey mapping, 5-minute script
│   └── PRODUCTION_ROADMAP.md # Enterprise hardening roadmap (OAuth, Postgres, Alembic)
├── frontend/                 # Next.js 15 SPA Operations Console (App Router)
│   ├── src/app/              # App router pages: Queue (/), Ticket Detail (/ticket/[id]), Insights (/insights)
│   ├── src/components/       # Reusable UI components (Badges, TopNav)
│   ├── src/context/          # Demo auth UserContext provider
│   └── src/lib/              # Typed API client, TypeScript definitions
├── scripts/                  # Operational scripts (dev DB verification, smoke test)
├── services/                 # Decoupled sidecars (Planned specifications, not built in reference release)
│   ├── realtime-go/          # Go SSE Realtime Gateway (planned, not built; active: resilient 30s jittered polling)
│   ├── engine-rust/          # Rust SLA & Scoring Engine (planned, not built; active: Python travel SLA & scoring engine with SQL index pushdown)
│   └── export-go/            # Go CSV Export Service (planned, not built; active: FastAPI streaming generator with cursor pagination)
├── .github/workflows/ci.yml  # GitHub Actions automated CI workflow
├── docker-compose.yml        # Multi-service composition (UNVERIFIED not built)
├── SECURITY.md               # Security policy & vulnerability reporting
├── requirements.txt          # Python dependencies
├── requirements.lock         # Pinned Python dependencies (pip freeze)
└── README.md                 # System overview and quickstart
```

---

## 🛠️ Developer Tooling & Operations CLI

OpsDesk includes standard developer workflows and terminal tools:

```bash
# Terminal Operations Queue Inspector
python scripts/opsdesk_cli.py queue --limit 10

# Inspect Case 360 Details, Booking Linkage, and Supplier Side-Threads
python scripts/opsdesk_cli.py inspect TCK-1001

# Inspect Top Root Cause Themes
python scripts/opsdesk_cli.py themes --days 7

# Run using Makefile
make install        # Install requirements for Python and Node.js
make dev-backend    # Start FastAPI on port 8000
make dev-frontend   # Start Next.js on port 3000
make test           # Run pytest suite
```

---

## ⚠️ Known Limitations

- **Realtime Updates:** The frontend queue currently uses resilient 30-second jittered polling to refresh ticket and SLA state; the high-concurrency Go SSE realtime gateway (`services/realtime-go/`) is planned, not built.
- **Rust Scoring Engine:** Dynamic SLA calculations and queue rankings are executed via the Python travel SLA and scoring engine (`backend/services/sla_engine.py`, `backend/services/routing_engine.py`) with SQL index pushdown; the compiled Rust engine sidecar (`services/engine-rust/`) is planned, not built.
- **Go Export Sidecar:** Streaming CSV export is handled by the FastAPI streaming generator (`GET /api/export/tickets.csv`) with cursor pagination; the dedicated Go CSV export service (`services/export-go/`) is planned, not built.
- **Ticket Search:** Search querying covers `tboh_id`, `id`, and `title`; wildcard searching across large `description` text bodies is omitted to prevent unindexed full table scans across high-volume operational databases.
- **Multi-Node Rate Limiting:** An in-memory sliding window limiter is active by default; a distributed Redis backend is supported via `RATE_LIMIT_BACKEND=redis` (with `REDIS_URL`), but a standalone Redis server is not provisioned in local dev.
- **Production Database:** The system runs on SQLite with WAL mode by default; PostgreSQL connection pooling and Alembic baseline migrations are implemented, but deploying to PostgreSQL requires setting `DATABASE_URL`.
- **Authentication Modes:** OpsDesk supports dual authentication: `AUTH_MODE=demo` (`X-User-Id` header for hackathon judges) and `AUTH_MODE=jwt` (Bearer tokens with bcrypt password hashing). Startup in production (`APP_ENV=production`) strictly refuses demo mode with a `RuntimeError` unless overridden by `ALLOW_DEMO_AUTH=true`. In `AUTH_MODE=jwt`, production startup requires an explicit non-default `JWT_SECRET` (>= 32 chars) and an allowed algorithm (`HS256`, `HS384`, `HS512`).

---

## 🔒 Security & Data Governance

- **Security Policy:** Details regarding multi-tenant agency isolation, vulnerability reporting, and demo auth migration are documented in [`SECURITY.md`](SECURITY.md).
- **Data Retention:** Tiered retention policies (Hot, Warm, Cold) and compliance boundaries are detailed in [`docs/DATA_RETENTION.md`](docs/DATA_RETENTION.md).
- **Architecture & ADRs:** Key architectural decisions (FastAPI source of truth, transactional outbox, intent-aware SLA) are recorded in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/adr/`](docs/adr/).

---

## 📄 License

TBD (team decision pending)
