# OpsDesk Judge Q&A: Technical Defense & Architectural FAQ

This document addresses the top 12 technical questions evaluated by judges and system architects for the **TBO VoyageHack 4.0 OpsDesk Track**. All claims cite verified benchmarks in [`docs/PITCH_FACTS.md`](file:///C:/Users/yashp/projects/opsdesk-wt-round10/docs/PITCH_FACTS.md).

---

### Q1: How does OpsDesk maintain sub-millisecond triage queries when ticket volume grows to hundreds of thousands?
**Answer**:
OpsDesk uses database-level **partial indexing** (`ix_tickets_triage` and `ix_tickets_my_queue`) defined in Alembic migration `0005`. By indexing only active tickets (`status IN ('Open', 'Pending', 'In Progress')`) and including `queue_score DESC`, the index size remains tiny even as the historical table grows to millions of rows.
- **Measured Reality**: At **400,000 rows** in PostgreSQL 16, `EXPLAIN (ANALYZE, BUFFERS)` reveals execution latency of **0.322 ms** with **100% Index Scan**, **0 sequential scans**, and **0 in-memory sorts** (see `docs/verification/scale_transcript.txt`).

### Q2: How do you prevent SQLite database lock contention during peak concurrent operations?
**Answer**:
During local development and single-instance deployments with SQLite, OpsDesk configures three database-level PRAGMAs on every connection:
1. `PRAGMA journal_mode=WAL` (Write-Ahead Logging allows readers and writers to operate concurrently without blocking readers).
2. `PRAGMA busy_timeout=5000` (threads retry for up to 5,000ms instead of failing immediately).
3. `PRAGMA synchronous=NORMAL` (reduces fsync wait).
- **Measured Reality**: Multi-worker concurrent load testing with 10 parallel workers across 300+ mixed read/write requests recorded **0 database lock errors** with median latency of **14.2 ms** (see `docs/verification/loadtest.json`).

### Q3: How do you prevent SLA penalties when check-in date and cancellation deadlines (LCD) conflict?
**Answer**:
In travel operations, the **Last Cancellation Date (LCD)** is the financial point of no return for non-refundable supplier penalties. Our routing engine calculates an `effective_deadline_at = min(lcd_date, check_in_date)` for cancellation and refund intents.
- **Measured Reality**: A refund ticket with check-in in 5 days but LCD in 2 hours receives a score of **2,500.0**, strictly outranking an inquiry with check-in in 4 hours (Score: **1,300.0**), preventing supplier no-show charges ($500+ per booking).

### Q4: What happens when an external AI provider (Gemini) suffers an outage or API key is missing?
**Answer**:
OpsDesk implements a **deterministic 3-tier fallback architecture**:
1. Tier 1: Deterministic regex evaluation in strict precedence order for high-confidence operational intents (Refund, Cancellation, Date Amendment, Bedding Preference, Voucher Resend).
2. Tier 2: LLM inference (Gemini 2.5 Flash) with PII redaction and thread pool concurrency limits.
3. Tier 3: Safe fallback to `Unclassified` with manual agent tagging.
- **Measured Reality**: With `GEMINI_API_KEY` unconfigured, `POST /api/ai/suggest-intent` achieves **100% accuracy** on operational intents in **< 25 ms** with source tagged as `regex_rule` (see Scenario 5 in `docs/verification/demo_check.txt`).

### Q5: How does OpsDesk guarantee multi-tenant data privacy between competing travel agencies?
**Answer**:
Every ticket is tagged with an `agency_id`. When a user with the `Requester` role accesses the API, SQLAlchemy queries are strictly filtered by the authenticated user's `current_user.agency_id`.
- **Measured Reality**: If Requester `USR-201` (`AGY-001`) requests a ticket from `AGY-002`, the API strictly returns **404 Not Found** (the ticket appears non-existent rather than 403 Forbidden to prevent agency ID enumeration).

### Q6: When an agent transfers a ticket across departments, how do you preserve supplier communication threads?
**Answer**:
OpsDesk decouples tickets from supplier communications using a normalized entity model (`SideConversation` and `SideConversationRecipient`). Transfers reassign `tickets.assigned_to` and create an audit log entry, leaving `ticket_id` foreign keys and thread recipients completely untouched.
- **Measured Reality**: Across 3 consecutive reassignments (`USR-101` -> `USR-102` -> `USR-103` -> `USR-101`), all 3 supplier recipients (`reservations@`, `duty.mgr@`, `operations@`) remained 100% intact (see Scenario 3 in `docs/verification/demo_check.txt`).

### Q7: How do you prevent CSV spreadsheet formula injection vulnerabilities during bulk exports?
**Answer**:
Spreadsheet applications (Excel, Google Sheets) execute formulas if a cell starts with `=`, `+`, `-`, `@`, `\t`, or `\r`. OpsDesk routes all exported values through `sanitize_csv_cell()`, which prepends a safe single-quote (`'`) to any dangerous leading character.

### Q8: Why did you choose partial indexes over standard compound indexes in PostgreSQL?
**Answer**:
In production travel operations, 95%+ of tickets are closed historical records. Standard compound indexes (`status, assigned_to, queue_score`) index all 5,000,000+ historical rows, bloating index memory. Partial indexes with `WHERE assigned_to IS NULL AND status IN ('Open', 'Pending', 'In Progress')` only index the active unassigned working set (< 5% of rows), keeping the entire working index in RAM cache.

### Q9: How is accessibility (WCAG 2.1 AA) guaranteed for operations agents?
**Answer**:
OpsDesk includes automated Playwright axe-core regression testing across all 4 user portals in Light and Dark modes. Contrast ratios on muted secondary text were hardened to satisfy 4.5:1 minimums (e.g. `--text-disabled: #94A3B8`, `--brand-700: #FDBA74`).
- **Measured Reality**: **19/19 axe-core test configurations passed** with **0 critical, 0 serious, 0 moderate, and 0 minor violations**.

### Q10: How do you guarantee safe database migrations across SQLite and PostgreSQL?
**Answer**:
OpsDesk maintains Alembic migrations with dialect conditional checks (`engine.name == "postgresql"` vs `"sqlite"`). In migration `0004` and `0005`, trigram extensions and partial indexes are applied to PostgreSQL while SQLite relies on standard indexed b-trees. Both schemas pass `alembic upgrade head`, `downgrade base`, and `alembic check` with 0 diffs.

### Q11: How do you prevent React hydration errors in Next.js 14 across themes and SSR?
**Answer**:
Hydration mismatches were audited and eliminated at the design-system primitive layer:
1. `Drawer`, `Modal`, `Card`, and `Headline` subtitles use semantic `<div>` elements instead of `<p>` containers, preventing HTML spec violation crashes (`<div> cannot be a descendant of <p>`).
2. `Avatar` includes safe fallback guards for undefined initials or missing names.
3. Root layout uses `suppressHydrationWarning={true}` on the `<html>` root for theme-script injection.

### Q12: Why is the frontend configured on port 3100 rather than port 3000?
**Answer**:
In enterprise and hackathon environments, port 3000 is frequently occupied by background services, Docker containers, or platform daemons. To provide a zero-collision, turn-key evaluation experience for judges, OpsDesk configures port **3100** by default across `frontend/package.json`, `scripts/demo_reset.ps1`, and all documentation.
