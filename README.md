# OpsDesk: B2B Travel Operations Case Management Platform

OpsDesk replaces fragmented ticketing in travel operations with context-linked cases organized around travel reality:
- **First-Class TBOH Linkage:** Surfaces prior contacts sharing the same TBO Booking Reference (`TBOH_ID`) without third-party add-ons.
- **Travel-Aware SLA Engine:** Dynamically calculates countdowns based on guest check-in proximity and Last Cancellation Date (LCD).
- **2-Tier Routing Engine:** 
  - Tier 1: Selects available regional agents based on workload.
  - Tier 2: Ranks the operations queue based on check-in urgency and priority.
- **Transfer-Proof Supplier Threads:** Decouples supplier conversation recipients from assigned agents, preserving threads across transfers.
- **Uncapped Ops Data Path:** Eliminates artificial 3,000-row export barriers via direct database streaming.

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
| **MVP-1 · Context-rich tickets** | Page 5 | • Create tickets with title, description, agency identity, TBOH, priority, category/intent, travel fields (check-in/LCD)<br>• Link tickets by TBOH, agency, and/or intent without third-party apps<br>• Intent taxonomy: manual select + rule auto-suggest / lightweight ML<br>• Status flow: New → Open → Pending → Escalated → Resolved → Closed<br>• Activity timeline: status, assignment, links, escalations | **Backend implemented, UI pending** | Implemented in `backend/app/main.py` (`POST /api/tickets`, `GET /api/tickets/{id}`, intent classifier, and atomic `audit_logs`). Next.js 15 UI pending Milestone 2+. |
| **MVP-2 · Routing & ownership** | Page 5 | • Assign / reassign / unassign with clear ownership<br>• Beyond FIFO/LIFO: region/country desk match + time window + priority score + availability<br>• Views: triage (unassigned), my queue, by region, by intent, linked-case view<br>• Audit reason explaining why ticket was routed | **Backend implemented, UI pending** | Implemented in `backend/services/routing_engine.py` (Tier-1 regional workload routing + Tier-2 dynamic queue scoring) and `GET /api/tickets` views. Queue UI pending. |
| **MVP-3 · Side conversations** | Page 5 | • Side-conversation threads with explicit recipient lists (decoupled from assignee)<br>• Recipients stay correct and preserved after agent transfer<br>• Distinguish internal notes (`InternalNote`) vs external replies (`PublicReply`) | **Backend implemented, UI pending** | Implemented in `backend/app/main.py` (`/side-threads` endpoints, `/messages` endpoint, and `POST /api/tickets/{id}/transfer`). Thread viewer UI pending. |
| **MVP-4 · Travel-aware SLA & escalation** | Page 6 | • Dynamic SLA countdown using priority + check-in / LCD proximity<br>• At-risk / breached indicators on queue<br>• Escalate to Escalation Manager as a first-class action (reassigns to manager queue, logs on timeline) | **Backend implemented, UI pending** | Implemented in `backend/services/sla_engine.py` (contract parity via `contracts/golden_vectors.json`) and `POST /api/tickets/{id}/escalate`. Visual SLA badge UI pending. |
| **MVP-5 · Feedback / insight loop** | Page 6 | • Tag or extract themes (refund delay, supplier lag, cancellation penalty)<br>• Insights view: top themes this week + sample tickets<br>• Optional: suggested link to product / bug<br>• Stretch: AI assist that uses linked history | **Pending** | `TicketTheme` data model and seed fixture mappings created; clustering engine and top themes dashboard scheduled for Milestone 3. |
| **MVP-6 · Data access for ops** | Page 6 | • Persist tickets across refreshes<br>• Uncapped export / API beyond artificial 3K-row UX barrier<br>• Retention / archival strategy | **Pending** | Durable SQLite/PostgreSQL persistence implemented; export endpoint: FastAPI StreamingResponse (Milestone 3). |
| **MVP-7 · Roles & access** | Page 6 | • Requester (agency): own tickets only (internal notes, queue scores, and other agencies' data hidden)<br>• Agent: organization queues<br>• Escalation Manager: escalation queue + managerial actions<br>• Lead: governance & queue health views<br>• Demo-only auth: identity is client-supplied, not secure (PDF p6 allows demo auth) | **Backend implemented, UI pending** | Implemented in `backend/app/auth.py` and endpoint RBAC guards (401 on missing auth, 403 on cross-tenant access, internal field stripping for Requesters). UI login switcher pending. |

---

## Active FastAPI Endpoints
Verified against runtime routes in `backend/app/main.py`:

| Method | Path | Access / Role | Description |
|---|---|---|---|
| `POST` | `/api/ai/suggest-intent` | Internal Staff | Suggest intent category using regex heuristic rules or Gemini fallback |
| `GET` | `/api/tickets` | Requester / Staff | List tickets with SLA & queue score (views: `triage`, `my_queue`, `by_region`, `by_intent`, `linked`) |
| `POST` | `/api/tickets` | Requester / Staff | Create operations ticket with auto-linkage of shared TBOH references |
| `GET` | `/api/tickets/{ticket_id}` | Requester / Staff | Full ticket details (internal notes, queue score, and routing reason withheld from Requesters) |
| `POST` | `/api/tickets/{ticket_id}/assign` | Internal Staff | Assign ticket to internal agent |
| `POST` | `/api/tickets/{ticket_id}/unassign` | Internal Staff | Unassign ticket |
| `POST` | `/api/tickets/{ticket_id}/status` | Internal Staff | Transition ticket status in state machine (403 for Requesters, 409 on invalid transition) |
| `POST` | `/api/tickets/{ticket_id}/escalate` | Internal Staff | Escalate ticket to Escalation Manager with neutral audit routing reason |
| `POST` | `/api/tickets/{ticket_id}/transfer` | Internal Staff | Transfer ticket preserving all supplier side conversation recipients |
| `POST` | `/api/tickets/{ticket_id}/messages` | Requester / Staff | Post public reply or internal staff note (`InternalNote` forbidden for Requesters) |
| `GET` | `/api/tickets/{ticket_id}/side-threads` | Internal Staff | List supplier side conversations for ticket (403 for Requesters) |
| `POST` | `/api/tickets/{ticket_id}/side-threads` | Internal Staff | Create supplier side conversation with explicit recipient email list |
| `POST` | `/api/tickets/{ticket_id}/side-threads/{id}/messages` | Internal Staff | Post message to supplier side conversation |

---

## Datetime & Timezone Decision
The backend consistently utilizes naive UTC datetimes across SQLite persistence, routing calculations, and SLA evaluation. Incoming API request datetimes (whether supplied with 'Z', timezone offsets like '+05:30', or naive strings) are automatically parsed and normalized to naive UTC datetimes by Pydantic schema validators before database persistence or SLA calculations.
- In development (SQLite), datetimes are stored as ISO 8601 strings in UTC.
- In production (PostgreSQL), columns use `TIMESTAMP WITHOUT TIME ZONE` stored strictly in UTC to prevent daylight savings anomalies and database server timezone drift.
- Client applications (Next.js 15 frontend) receive ISO 8601 UTC strings and format them into local agency or agent timezones at presentation time.

---

## Pre-Demo Wall-Clock Reset
Because travel SLA countdowns and triage queue scores evaluate dynamically relative to current wall-clock time (`now`), run the reset command immediately prior to a live demonstration to calibrate all Journey fixtures:
```bash
python backend/seed/seed_data.py --reset
```
This recalibrates the key demonstration fixtures relative to execution time:

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

## Modular Architecture & Sidecar Contracts
The system is built as a modular monorepo with Python FastAPI as the core source of truth and decoupled sidecar extensions:

1. **Python FastAPI Backend (`backend/`):**
   - Source of truth for authentication, RBAC, CRUD, routing orchestration, and intent suggestions via Gemini (model target: Gemini 3.5 Flash-Lite [UNVERIFIED model name, availability date unverified; fallback: gemini-2.5-flash]).
2. **Go Realtime Gateway (`services/realtime-go/`):**
   - *Why it exists:* Provides high-concurrency Server-Sent Events (SSE) broadcasting from the `events_outbox` table (design target, benchmark pending).
   - *Python Fallback:* Client-side SWR polling / FastAPI long-polling (`REALTIME=off`).
3. **Rust SLA & Scoring Engine (`services/engine-rust/`):**
   - *Why it exists:* High-throughput batch re-evaluation of travel SLAs across active records (design target: sub-millisecond execution, benchmark pending).
   - *Python Fallback:* Pure-function reference implementation in `backend/services/sla_engine.py` (`SLA_ENGINE=python`).
4. **Go Export Service (`services/export-go/`):**
   - *Why it exists:* Low-memory streaming CSV exports for historical operations datasets (design target, benchmark pending).
   - *Python Fallback:* FastAPI `StreamingResponse` with generator chunking (`EXPORT=fastapi`).

---

## Monorepo Layout
```text
opsdesk/
├── backend/                  # FastAPI core application, services, tests, and seed generator
├── services/
│   ├── realtime-go/          # Go SSE Realtime Gateway (contracts & skeleton)
│   ├── engine-rust/          # Rust SLA & Scoring Engine (contracts & skeleton)
│   └── export-go/            # Go CSV Export Service (contracts & skeleton)
├── contracts/                # Shared JSON Schemas and Golden Vectors
├── docs/                     # Architecture & Design documentation
├── frontend/                 # Next.js 15 UI (Milestone 2+)
├── .env.example              # Environment configuration & feature flags
├── opsdesk.db                # SQLite local database (untracked, .gitignore)
├── pytest.ini                # Pytest configuration
└── README.md                 # System overview
```
