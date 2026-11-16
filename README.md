# OpsDesk: B2B Travel Operations Case Management Platform

OpsDesk replaces fragmented ticketing in travel operations with context-linked cases organized around travel reality:
- **First-Class TBOH Linkage:** Surfaces prior contacts sharing the same TBO Booking Reference (`TBOH_ID`) without third-party add-ons.
- **Travel-Aware SLA Engine:** Dynamically calculates countdowns based on guest check-in proximity and Last Cancellation Date (LCD).
- **2-Tier Routing Engine:** 
  - Tier 1: Emergency bypass for departures within 4 hours.
  - Tier 2: Continuous multi-factor dynamic queue scoring.
- **Transfer-Proof Supplier Threads:** Decouples supplier conversation recipients from assigned agents, preserving threads across transfers.
- **Uncapped Ops Data Path:** Eliminates artificial 3,000-row export barriers via direct database streaming (`yield_per`).
- **Complete Next.js 15 UI:** Operations queue, thread viewer, role switcher, intent auto-suggest, and analytics dashboard.

> **Intent-Aware SLA Rule & LCD Handling:**
> - `lcd_date` is optional/nullable across Pydantic schemas and database models (`Optional[datetime] = None`).
> - Urgency deadline is determined by operational intent:
>   - For cancellation-sensitive intents (`Refund Request`, `Cancellation Inconvenience`, `Unclassified`, or unspecified `None`), if `lcd_date` is present, effective deadline is `min(check_in_date, lcd_date)`.
>   - For other operational intents (e.g., `Emergency Check-in Assist`, `Voucher Resend`, `Date Amendment`, `Bedding / Room Preference`), cancellation deadlines are inapplicable and `check_in_date` strictly governs urgency.
> - In demo fixtures TCK-1004, TCK-1006, and TCK-1007 (check-in assist / voucher resend), `lcd_date` is `None`. Active Refund and Cancellation demo tickets are seeded with future LCDs (`now < lcd <= check_in`).

---

## MVP Implementation Status (Mapped to PDF Pages 5–6)
This checklist strictly tracks the requirements specified in *Zendesk-Darwin box Automation.pdf* (Pages 5–6):

| MVP # & Name | Source (PDF Page) | Specification & Core Bullets | Status | Implementation Details |
|---|---|---|---|---|
| **MVP-1 · Context-rich tickets** | Page 5 | • Create tickets with title, description, agency identity, TBOH, priority, category/intent, travel fields (check-in/LCD)<br>• Link tickets by TBOH, agency, and/or intent without third-party apps<br>• Intent taxonomy: manual select + rule auto-suggest / lightweight ML<br>• Status flow: New → Open → Pending → Escalated → Resolved → Closed<br>• Activity timeline: status, assignment, links, escalations | **Fully Implemented** | Backend: `POST /api/tickets`, `GET /api/tickets/{id}`, rule classifier, atomic audit logs.<br>Frontend: Create Ticket Modal with Auto-Suggest Intent, Ticket Detail Activity Timeline. |
| **MVP-2 · Routing & ownership** | Page 5 | • Assign / reassign / unassign with clear ownership<br>• Beyond FIFO/LIFO: region/country desk match + time window + priority score + availability<br>• Views: triage (unassigned), my queue, by region, by intent, linked-case view<br>• Audit reason explaining why ticket was routed | **Fully Implemented** | Backend: Tier-1 emergency bypass + Tier-2 dynamic queue scoring.<br>Frontend: Queue page with Triage, Assigned to Me, and My Tickets tabs, plus search & intent filter. |
| **MVP-3 · Side conversations** | Page 5 | • Side-conversation threads with explicit recipient lists (decoupled from assignee)<br>• Recipients stay correct and preserved after agent transfer<br>• Distinguish internal notes (`InternalNote`) vs external replies (`PublicReply`) | **Fully Implemented** | Backend: `/side-threads` endpoints, message types, and recipient preservation on transfer.<br>Frontend: Thread toggle (Public Reply vs Internal Note) + Supplier side-thread composer. |
| **MVP-4 · Travel-aware SLA & escalation** | Page 6 | • Dynamic SLA countdown using priority + check-in / LCD proximity<br>• At-risk / breached indicators on queue<br>• Escalate to Escalation Manager as a first-class action (reassigns to manager queue, logs on timeline) | **Fully Implemented** | Backend: `sla_engine.py` (effective deadline helper) + `POST /api/tickets/{id}/escalate`.<br>Frontend: Visual SLA badges (`NORMAL`, `AT_RISK`, `BREACHED`) with countdowns & escalation action. |
| **MVP-5 · Feedback / insight loop** | Page 6 | • Tag or extract themes (refund delay, supplier lag, cancellation penalty)<br>• Insights view: top themes this week + sample tickets<br>• Optional: suggested link to product / bug<br>• Stretch: AI assist that uses linked history | **Fully Implemented** | Backend: `GET /api/insights/themes` + `POST /api/tickets/{id}/link-suggestion`.<br>Frontend: `/insights` analytics dashboard showing recurring themes, percentage bars, and sample ticket links. |
| **MVP-6 · Data access for ops** | Page 6 | • Persist tickets across refreshes<br>• Uncapped export / API beyond artificial 3K-row UX barrier<br>• Retention / archival strategy | **Fully Implemented** | Backend: Memory-safe `yield_per(500)` streaming generator (`GET /api/export/tickets.csv`), tested 5,000 rows in ~1.32s; `docs/DATA_RETENTION.md`.<br>Frontend: "Export CSV (MVP-6)" streaming download button. |
| **MVP-7 · Roles & access** | Page 6 | • Requester (agency): own tickets only (internal notes, queue scores, and other agencies' data hidden)<br>• Agent: organization queues<br>• Escalation Manager: escalation queue + managerial actions<br>• Lead: governance & queue health views<br>• Demo-only auth: identity is client-supplied, not secure (PDF p6 allows demo auth) | **Fully Implemented** | Backend: RBAC guards with 401/403 responses and internal field stripping.<br>Frontend: Top navigation Role Switcher with visible Demo-Auth banner and route guards. |

---

## Quickstart Guide

### Prerequisites
- Python 3.11+
- Node.js 18+ (tested on Node v24)
- SQLite3 (included with Python)

### 1. Database Setup & Seeding
```powershell
# In repository root
python -m backend.seed.seed_data --reset
```
*Seeds the development database (`opsdesk.db`) with 5,000 realistic operations tickets, calibrating Journey fixtures TCK-1001 through TCK-1008.*

### 2. Run Backend API
```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation: `http://127.0.0.1:8000/docs`

### 3. Run Frontend UI
```powershell
cd frontend
npm install
npm run dev
```
Open Browser: `http://localhost:3000`

---

## Test & Verification Commands

All test and verification commands are 100% deterministic and runnable locally:

```powershell
# 1. Backend Unit & Integration Tests (68 passed)
pytest backend/tests -q

# 2. Frontend ESLint Check
cd frontend ; npm run lint

# 3. Frontend Production Build & Typecheck
cd frontend ; npm run build

# 4. Frontend-Backend Contract Integration Smoke Test
python scripts/smoke_frontend_api.py
```

---

## Active Environment Variables & Feature Flags

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ALLOWED_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Origins permitted by FastAPI CORSMiddleware |
| `OPSDESK_DEV_DB` | `opsdesk.db` | Path or connection string to the SQLite database |
| `SLA_ENGINE` | `python` | Toggle between Python reference implementation and Rust sidecar (`python` \| `rust`) |
| `REALTIME` | `off` | Toggle between client-polling and Go SSE sidecar (`off` \| `on`) |
| `EXPORT` | `fastapi` | Toggle between FastAPI StreamingResponse and Go daemon (`fastapi` \| `go`) |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Frontend backend API target URL |

---

## Pre-Demo Wall-Clock Reset & Fixture Calibrations

Because travel SLA countdowns and triage queue scores evaluate dynamically relative to current wall-clock time (`now`), run the reset command immediately prior to a live demonstration to calibrate all Journey fixtures:
```bash
python -m backend.seed.seed_data --reset
```

| Ticket ID | Journey Mapping | PDF p7 Status | Intent | Priority | Status | Urgency / Deadlines | Expected SLA | Queue Position |
|---|---|---|---|---|---|---|---|---|
| **`TCK-1001`** | Journey A | Verified (PDF p7) | Refund Request | High | Closed | Check-in -14d, LCD -16d | STOPPED (Gray) | Closed (n/a) |
| **`TCK-1002`** | Journey A | Verified (PDF p7) | Refund Request | Medium | Closed | Check-in -4d, LCD -6d | STOPPED (Gray) | Closed (n/a) |
| **`TCK-1004`** | Journey B | Verified (PDF p7) | Emergency Check-in Assist | Urgent | Open | Check-in ~2.5h, LCD None | AT_RISK (Amber) | Assigned USR-101 |
| **`TCK-1005`** | Journey C | Verified (PDF p7) | Bedding / Room Preference | Medium | Open | Check-in +3d, LCD None | NORMAL (Green) | Assigned USR-101 (Side Convo) |
| **`TCK-1006`** | Journey D | Verified (PDF p7) | Emergency Check-in Assist | Urgent | Open | Check-in ~45m, LCD None | AT_RISK (Amber) | Assigned USR-101 |
| **`TCK-1007`** | Journey B (Unassigned) | Verified (PDF p7) | Emergency Check-in Assist | Urgent | New | Check-in ~2.25h, LCD None | AT_RISK (Amber) | **#1 in Triage Queue** (Score 1800.0) |
| **`TCK-1008`** | Demo Fixture (Refund LCD) | **UNVERIFIED** (PDF p7 letter unverified) | Refund Request | High | Open | Check-in +5d, LCD ~3.0h | **AT_RISK (Amber)** (via LCD) | Assigned USR-101 (Score 1300.0) |

---

## Monorepo Layout
```text
opsdesk/
├── backend/                  # FastAPI core application, domain services, tests, and seed generator
│   ├── app/                  # FastAPI router, models, schemas, auth dependencies
│   ├── seed/                 # Realistic 5,000-ticket generator with Journey fixtures
│   ├── services/             # Intent classifier, routing engine, travel SLA engine
│   └── tests/                # Test suite (68 tests)
├── contracts/                # Shared JSON Schemas, Golden Vectors, openapi.json
├── docs/                     # Architecture documentation
│   ├── adr/                  # 5 Architectural Decision Records (ADR 0001 - 0005)
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
├── services/                 # Decoupled sidecar specifications (Go SSE, Rust SLA, Go Export)
├── .github/workflows/ci.yml  # GitHub Actions automated CI workflow
├── docker-compose.yml        # Multi-service composition (UNVERIFIED not built)
├── pytest.ini                # Pytest configuration
├── requirements.txt          # Python dependencies
└── README.md                 # System overview and quickstart
```
