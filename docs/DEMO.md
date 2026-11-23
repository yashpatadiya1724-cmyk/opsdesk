# OpsDesk 5-Minute Judge Demo Walkthrough

This guide provides an end-to-end walkthrough for judges and evaluators of the **TBO VoyageHack 4.0 OpsDesk Track**. It demonstrates how OpsDesk solves high-stakes travel operations challenges with sub-millisecond triage, multi-tenant isolation, thread preservation, and massive scalability.

---

## Quick Setup (1-Click Reset)

Run the automated reset script from PowerShell:
```powershell
.\scripts\demo_reset.ps1
```
This script:
1. Stops any stray processes on port **8000** (backend) and **3100** (frontend).
2. Backs up the dev database and reseeds base test fixtures (50 tickets).
3. Launches the FastAPI backend (`http://localhost:8000`) and Next.js frontend (`http://localhost:3100`).

### Demo User Accounts (Password: `demo123` for all)
- **Operations Agent**: `aisha@travelops.example.com` (`USR-101`) - Frontline triage & response
- **Escalation Manager**: `vikram.esc@travelops.example.com` (`USR-103`) - Priority SLA intervention
- **Operations Lead**: `priya@travelops.example.com` (`USR-104`) - Team analytics, bulk export & rule audits
- **Agency Requester**: `agent@voyage.example.com` (`USR-201`, Agency: `AGY-001`) - B2B portal

---

## Walkthrough Scenarios (5-Minute Script)

### Step 1: Frontline Triage & Case Linkage (Claim A)
**Goal**: Show how OpsDesk groups fragmented booking requests into a unified contact chain.
1. Log into the frontend at `http://localhost:3100` as **Aisha (Agent)** (`aisha@travelops.example.com`).
2. In the Queue list, observe ticket **`TCK-1008`** (Booking Reference: **`TBOH-89104`**).
3. Click into **`TCK-1008`**:
   - **Linked Contacts**: The "Related Booking History" side-drawer reveals 3 connected cases (`TCK-1001`, `TCK-1002`, `TCK-1008`) under booking `TBOH-89104`.
   - **SLA Urgency**: The SLA badge indicates **`AT_RISK`** with an imminent deadline.
   - **Triage Priority**: Notice that this ticket ranks **#2** in unassigned triage queue with a priority score of `1690.0`.

### Step 2: Intelligent Deadline Precedence (Claim B)
**Goal**: Demonstrate that OpsDesk prioritizes non-refundable supplier deadlines (LCD) over distant check-in dates.
1. In the Triage Queue, look at **`TCK-DEMO-LCD`** vs **`TCK-DEMO-CIN`**:
   - **Ticket A (`TCK-DEMO-LCD`)**: Refund request for a booking with check-in 5 days away, but the **Last Cancellation Date (LCD)** is in **2 hours**. Queue Score: **2,500.0**.
   - **Ticket B (`TCK-DEMO-CIN`)**: Standard inquiry with check-in in 4 hours, but no cancellation deadline. Queue Score: **1,300.0**.
2. **Outcome**: OpsDesk elevates the LCD ticket to the top of the queue, preventing costly supplier no-show penalties ($500+ per booking).

### Step 3: Supplier Liaison Side-Threads (Claim C)
**Goal**: Verify that multi-party supplier communications survive agent reassignments.
1. Open ticket **`TCK-1005`** which has an active supplier negotiation with hotel reservations.
2. In the **Supplier Liaison** tab, note the 3 external recipients:
   - `reservations@vendor.example.com`
   - `duty.mgr@vendor.example.com`
   - `operations@vendor.example.com`
3. Click **Transfer Ticket** -> Assign to **Bob (`USR-102`)** with note *"Passing to morning shift"*.
4. Switch to Bob or Lead, and transfer to **Vikram (`USR-103`)**, then back to **Aisha (`USR-101`)**.
5. **Outcome**: The supplier thread, entire audit message history, and all 3 recipient addresses remain completely intact with zero data loss.

### Step 4: Scale Export Beyond 3K Barrier (Claim D)
**Goal**: Prove streaming export handles 50,000 tickets without crashing browser or server memory.
1. Log in as **Priya (Lead)** (`priya@travelops.example.com`).
2. Navigate to **Team Analytics & Export** (`http://localhost:3100/analytics` or `/export`).
3. Click **Export All Tickets (CSV)** or execute via API:
   ```bash
   curl -H "X-User-Id: USR-104" http://localhost:8000/api/export/tickets.csv -o export_50k.csv
   ```
4. **Outcome**: 50,000 tickets stream cleanly using HTTP chunked transfer. Server peak memory stays below **17 MB** (vs 500+ MB in unbatched implementations).

### Step 5: Zero-Key AI Fallback & Resilience (Claim E)
**Goal**: Show that ticket intent classification works 100% reliably even when third-party AI APIs are down or unconfigured.
1. Open ticket creation or intent suggestion tester (`POST /api/ai/suggest-intent`).
2. Submit a cancellation request with zero `GEMINI_API_KEY` configured in the environment.
3. **Outcome**: OpsDesk’s deterministic regex classification engine immediately tags the ticket as `Refund Request` in **< 25 ms** with source `regex_rule`.

### Step 6: Multi-Tenant Tenant Isolation & RBAC (Claim F)
**Goal**: Demonstrate enterprise multi-tenancy and data segregation.
1. Log in as **Agency Requester** (`agent@voyage.example.com` from `AGY-001`).
2. Notice the queue view strictly shows tickets originating from **`AGY-001`**.
3. Attempting to access an `AGY-002` ticket directly via URL (`/ticket/TCK-2000`) or API returns **404 Not Found** (the case does not exist for this tenant).
4. Attempting to call the Lead export endpoint returns **403 Forbidden**.

### Step 7: Automated Verification Check
At any time, run the automated end-to-end verification script:
```powershell
python scripts/demo_check.py --port 3100
```
This script runs through all 6 scenarios in **< 90 seconds** and generates a fresh transcript at `docs/verification/demo_check.txt`.

---

## Audited Production Metrics (PITCH FACTS)
Refer to [`docs/PITCH_FACTS.md`](file:///C:/Users/yashp/projects/opsdesk-wt-round10/docs/PITCH_FACTS.md) for full benchmarks:
- **Triage Query Latency (400k rows)**: 0.322 ms (100% Index Scan, 0 Seq Scan)
- **Concurrent Load**: 0 SQLite locks across 300+ multi-worker requests
- **Accessibility**: 19/19 axe-core audits pass with 0 violations
- **Test Suites**: 164 SQLite tests, 17 PostgreSQL tests, 31 Vitest tests all passing
