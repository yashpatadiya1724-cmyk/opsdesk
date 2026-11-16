# OpsDesk Architecture Specification

## 1. System Overview & Core Principles

OpsDesk is an enterprise B2B travel operations platform designed for high-volume agency ticket dispatching, LCD-aware (Last Cancellation Date) SLA compliance, and two-tier deterministic routing.

The platform enforces a strict **Single Source of Truth** model:
- **FastAPI Core Backend** owns all business logic, validation, transactional persistence, and authorization.
- **Next.js 15 App Router Frontend** provides the operations console for agents, leads, and requesters.
- **Sidecar architecture** (Go SSE daemon, Rust SLA acceleration) is specified with native Python reference engines as zero-dependency defaults.

---

## 2. System Context Diagram (Mermaid)

```mermaid
flowchart TD
    subgraph Clients["Client Tier"]
        AgentUI["Next.js Operations Console\n(Agents / Leads / Managers)"]
        ReqUI["Travel Agency Portal\n(B2B Requesters)"]
    end

    subgraph Platform["OpsDesk Core Platform"]
        API["FastAPI Dispatcher Backend\n(Port 8000)"]
        SLA["SLA & Routing Engine\n(Effective Deadline & Two-Tier Routing)"]
        Rules["Rule-First Intent Classifier\n(+ Gemini Flash Fallback)"]
        Outbox["Transactional Outbox\n(events_outbox table)"]
    end

    subgraph DataTier["Data Tier"]
        DB[(Relational DB\nSQLite Dev / PostgreSQL Prod)]
    end

    subgraph External["External Services (Optional Sidecars)"]
        GoSSE["Go SSE Realtime Gateway\n(Planned / Feature-flagged)"]
        GeminiAPI["Google Gemini API\n(Intent Suggestion Fallback)"]
    end

    AgentUI -->|REST + Polling\nHTTP :8000| API
    ReqUI -->|REST Scoped\nHTTP :8000| API
    API --> SLA
    API --> Rules
    API -->|Atomic Write| Outbox
    API -->|CRUD & yield_per streaming| DB
    Rules -.->|Unclassified only| GeminiAPI
    Outbox -.->|CDC Poll (Optional)| GoSSE
    GoSSE -.->|SSE Stream| AgentUI
```

---

## 3. Component Architecture Diagram (Mermaid)

```mermaid
flowchart LR
    subgraph Frontend["Frontend (Next.js 15 SPA)"]
        QueueView["Queue Page\n(Triage / Assigned / My)"]
        DetailView["Ticket Detail\n(Thread Split & Actions)"]
        InsightsView["Insights Dashboard\n(Themes & CSV Export)"]
        UserCtx["User Context\n(Demo Auth Switcher)"]
    end

    subgraph BackendApp["FastAPI Backend (/api)"]
        AuthDep["Auth Dependency\n(X-User-Id / Role Resolution)"]
        TicketRouter["Ticket Router\n(/api/tickets)"]
        InsightsRouter["Insights Router\n(/api/insights/themes)"]
        ExportRouter["Export Streaming Router\n(/api/export/tickets.csv)"]
        AIRouter["AI Suggest Router\n(/api/ai/suggest-intent)"]
    end

    subgraph Services["Core Domain Services"]
        Classifier["intent_classifier.py\n(INTENT_TAXONOMY)"]
        SLAEngine["sla_engine.py\n(effective_deadline_hours)"]
        RouterEngine["routing_engine.py\n(calculate_queue_score_tier2)"]
    end

    Frontend -->|HTTP Requests| AuthDep
    AuthDep --> TicketRouter
    AuthDep --> InsightsRouter
    AuthDep --> ExportRouter
    AuthDep --> AIRouter
    TicketRouter --> SLAEngine
    TicketRouter --> RouterEngine
    AIRouter --> Classifier
```

---

## 4. Entity-Relationship Diagram (ERD Mermaid)

```mermaid
erDiagram
    AGENCIES ||--o{ USERS : employs
    AGENCIES ||--o{ TICKETS : submits
    USERS ||--o{ TICKETS : assigned_to
    TICKETS ||--o{ TICKET_MESSAGES : contains
    TICKETS ||--o{ SIDE_CONVERSATIONS : has
    SIDE_CONVERSATIONS ||--o{ SIDE_MESSAGES : contains
    TICKETS ||--o{ AUDIT_LOGS : records
    TICKETS ||--o{ EVENTS_OUTBOX : emits

    AGENCIES {
        string id PK
        string name
        string tier
        datetime created_at
    }

    USERS {
        string id PK
        string email
        string name
        string role
        string agency_id FK
        datetime created_at
    }

    TICKETS {
        string id PK
        string tboh_id UK
        string agency_id FK
        string title
        string description
        string intent
        string priority
        string status
        string assigned_agent_id FK
        datetime check_in_date
        datetime lcd_date
        string suggested_bug_link
        string linked_ticket_ids
        datetime created_at
        datetime updated_at
    }

    TICKET_MESSAGES {
        string id PK
        string ticket_id FK
        string sender_id FK
        string message_type
        text content
        datetime created_at
    }

    SIDE_CONVERSATIONS {
        string id PK
        string ticket_id FK
        string supplier_name
        string subject
        text recipients
        string created_by FK
        datetime created_at
    }

    SIDE_MESSAGES {
        string id PK
        string side_conversation_id FK
        string sender_id FK
        text body
        datetime created_at
    }

    AUDIT_LOGS {
        string id PK
        string ticket_id FK
        string actor_id FK
        string action
        text details_json
        datetime created_at
    }

    EVENTS_OUTBOX {
        string id PK
        string event_type
        string ticket_id FK
        string agency_id FK
        string visibility
        text payload_json
        datetime created_at
        datetime delivered_at
    }
```

---

## 5. Ticket Lifecycle State Machine (Mermaid)

```mermaid
stateDiagram-v2
    [*] --> New : Created via POST /api/tickets
    New --> Open : Assigned or First Staff Reply
    New --> Pending : Waiting on Customer/Agency
    New --> Escalated : SLA Threshold Breached or Manual Escalate
    New --> Closed : Resolved directly

    Open --> Pending : Waiting on Supplier/Customer
    Open --> Escalated : Critical Issue / SLA Risk
    Open --> Closed : Issue Resolved

    Pending --> Open : Customer Replied / Data Provided
    Pending --> Escalated : Deadline Approaching
    Pending --> Closed : Inactive / Completed

    Escalated --> Open : De-escalated by Manager
    Escalated --> Closed : Resolved by Escalation Team

    Closed --> Open : Reopened on Customer Follow-up
    Closed --> [*]
```

---

## 6. Role-Based Access Control (RBAC) Security Matrix

| Action / Endpoint | Requester (Agency) | Agent (Staff Tier 1) | EscalationManager (Staff Tier 2) | Lead (Leadership) |
| :--- | :---: | :---: | :---: | :---: |
| **GET /api/tickets (triage view)** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **GET /api/tickets (assigned_to_me)** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **GET /api/tickets (my_tickets)** | ✅ Scoped to own Agency | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **GET /api/tickets/{id}** | ✅ Scoped (own Agency only) | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets** | ✅ Allowed (own Agency) | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/assign** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/unassign** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/transfer** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/escalate** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/status** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/messages (PublicReply)** | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/messages (InternalNote)** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/side-threads** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **GET /api/tickets/{id}/side-threads** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **POST /api/tickets/{id}/link-suggestion** | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **GET /api/insights/themes** | ❌ 403 Forbidden | ❌ 403 Forbidden | ✅ Allowed | ✅ Allowed |
| **GET /api/export/tickets.csv** | ❌ 403 Forbidden | ❌ 403 Forbidden | ❌ 403 Forbidden | ✅ Allowed |

---

## 7. Configuration & Feature Flags

Sidecars and modular subsystems are configured via environment variables:

| Variable | Values | Default | Active Implementation | Description |
| :--- | :--- | :--- | :--- | :--- |
| `SLA_ENGINE` | `python` \| `rust` | `python` | Native Python reference | Pure functional calculation of travel SLA deadline and queue priority score. |
| `REALTIME` | `off` \| `on` | `off` | SWR / Client Polling (15s) | When `off`, UI uses polling. When `on`, connects to Go SSE gateway reading `events_outbox`. |
| `EXPORT` | `fastapi` \| `go` | `fastapi` | FastAPI `StreamingResponse` | Uses SQLAlchemy `yield_per(500)` generator. Tested: 5,000 rows in ~1.32s with zero buffering. |
| `ALLOWED_CORS_ORIGINS` | CSV of origins | `http://localhost:3000` | FastAPI CORSMiddleware | Controls allowed origins for browser AJAX/fetch requests. |
| `OPSDESK_DEV_DB` | File path | `./opsdesk.db` | SQLite / PostgreSQL | Target connection string or local database file path. |

---

## 8. Scaling Design Targets

> [!NOTE]
> The performance metrics below represent **architectural design targets** for enterprise scale, not measured lab benchmarks (except where explicitly noted as verified).

1. **Queue Dispatching Throughput:**
   - *Design Target:* 10,000 active tickets evaluated in < 50ms under Rust SLA engine; < 250ms under Python reference engine.
   - *Verified In Lab:* 5,000 seeded tickets loaded in memory and scored deterministically across two tiers.

2. **Uncapped CSV Export:**
   - *Design Target:* 50,000+ tickets streamed to disk/client without memory spike (< 50MB RSS).
   - *Verified In Lab:* 5,000 seeded tickets streamed via FastAPI `yield_per(500)` in **1.32 seconds** with constant low memory footprint.

3. **Database Write Concurrency:**
   - *Design Target:* 500 writes/second with row-level locks on PostgreSQL (planned production tier).
