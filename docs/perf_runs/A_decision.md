# A8 Decision Note: Performance Collapse Diagnosis & Part B Candidates

**Date**: 2026-11-18  
**Branch**: `perf/m5-collapse-diagnosis`  
**Host Machine**: Windows 11, 12 Logical Cores (`$env:NUMBER_OF_PROCESSORS=12`), Python 3.11.9  
**Server Architecture**: Single Uvicorn worker, SQLite loopback, AnyIO default threadpool (40 tokens), SQLAlchemy QueuePool (`pool_size=10`, `max_overflow=20`, `pool_timeout=30s`).

---

## 1. Summary of Empirical Diagnosis (A1–A7)

1. **A1 (Engine & Server Configuration)**:
   - SQLAlchemy QueuePool configured with `pool_size=10`, `max_overflow=20`, and `pool_timeout=30.0`s. Total connection ceiling = 30 connections.
   - AnyIO default threadpool limiter has `total_tokens = 40`.
   - All primary API endpoints in `backend/app/main.py` are synchronous (`def`), dispatched directly to AnyIO worker threads.
   - Uvicorn runs single worker (`workers=1`), default `--limit-concurrency` unset (infinite queueing).

2. **A2 & A3 (Thread State and QueuePool Saturation)**:
   - At 100 concurrent closed-loop clients ($T=0$), QueuePool checked-out connections quickly saturate at 30/30 (`Current Checked out connections: 30`, `Current Overflow: 20`, `Connections in pool: 0`).
   - Active threads climb to 43+.
   - Out of 43 threads, faulthandler trace dumps (`docs/perf_runs/A2_classification_summary.txt`) reveal **360 thread blocks classified as `pool checkout wait`** inside SQLAlchemy's `_do_get` method (`sqlalchemy/pool/base.py`).
   - Because `pool_timeout` is 30 seconds, excess threads wait up to 30 seconds before timing out, causing client-side requests to hit the 30s deadline and fail with status 599.

3. **A4 (CPU & Client Verification)**:
   - Server process CPU spikes to 80–100% of a single core (single-process Python GIL saturation during heavy scoring/serialization).
   - Client process CPU remains under 20% across all runs. The client harness is not the bottleneck.

4. **A5 (Cache ON vs Cache OFF Comparison)**:
   - At 100 concurrent clients ($T=0$), Cache-ON and Cache-OFF behave almost identically:
     - Variant (a): Cache-OFF median 2.3 RPS, p50 36,260.6 ms vs Cache-ON median 2.4 RPS, p50 36,127.8 ms (300 timeouts out of 317/318 requests).
     - Variant (b): Cache-OFF median 2.3 RPS, p50 36,157.5 ms vs Cache-ON median 2.2 RPS, p50 37,146.6 ms (300 timeouts).
   - Root Cause: In a realistic workload mix with 10% writes (5% creates, 5% assigns), the cache is continuously invalidated. Under 100 concurrent clients, thundering herd misses force repeated expensive full-table queries and scoring.

5. **A6 (Triage Execution Breakdown on Variant b - 5,000 unassigned rows)**:
   - Median total request duration: 83.38 ms.
   - DB Fetch & ORM Hydration: 53.60 ms (**64.3% of total request time**).
   - cProfile confirms 57.4 ms cumulative spent inside SQLAlchemy ORM instance mapping (`loading.py:1075(_instance)` and `_populate_full`) instantiating 5,000 full `Ticket` model objects.
   - Python queue scoring: 25.38 ms (30.4%).
   - Sorting: 4.25 ms (5.1%).

6. **A7 (Triage Cache Security & Invalidation Verification)**:
   - Evaluated cache key structure in `backend/app/main.py` line 341.
   - Comprehensive tests implemented in `backend/tests/test_triage_cache_security.py`:
     1. Agency A vs Agency B tenant isolation: PASSED.
     2. Staff vs Requester internal fields (`queue_score`, `routing_reason`) stripping: PASSED.
     3. Write-time cache invalidation on ticket creation, assignment, and status update: PASSED.
   - Zero security regressions identified.

---

## 2. Evaluation of Part B Candidates (B1–B4)

### Candidate B1: QueuePool Optimization & Timeout Handling
- **Empirical Evidence**: A1, A2, and A3 prove that QueuePool reaches its 30-connection ceiling while AnyIO runs 40+ threads. Threads block in `_do_get` for up to 30 seconds before timing out, triggering 599 client errors.
- **Proposed Change**:
  1. Tune `DB_POOL_SIZE` to 30, `DB_MAX_OVERFLOW` to 20 (total capacity 50), and reduce `DB_POOL_TIMEOUT` from 30.0s to 5.0s.
  2. Add a dedicated FastAPI exception handler for `sqlalchemy.exc.TimeoutError` returning HTTP `503 Service Unavailable` with `Retry-After: 5`.
- **Verdict**: **APPROVED**.

### Candidate B2: Bounded Concurrency & Load Shedding
- **Empirical Evidence**: A5 showed that under 100 concurrent clients with $T=0$, unthrottled requests queue indefinitely, driving p50 latency over 36,000 ms and producing ~94% client timeouts (599). In contrast, `A_limiter_defaults_on.txt` proved that rejecting excess traffic maintains low p50 latency (51.5 ms) without server hang.
- **Proposed Change**:
  1. Introduce an in-flight concurrency semaphore / bounded queue in the application layer.
  2. When saturated, immediately reject excess requests with HTTP `503 Service Unavailable` and `Retry-After: 2`, while explicitly exempting `/health` and `/ready` probes.
- **Verdict**: **APPROVED**.

### Candidate B3: Triage Query Projection (`load_only` / Column Tuples)
- **Empirical Evidence**: A6 demonstrated that 64.3% (53.60 ms) of triage execution is wasted on SQLAlchemy full ORM object instantiation for 5,000 tickets, when scoring only requires `id`, `priority`, `check_in_date`, `lcd_date`, `intent`, `created_at`, `status`, and `agency_id`.
- **Proposed Change**:
  1. Optimize `list_tickets` when sorting by triage score to fetch only required projection columns.
  2. Perform in-memory scoring and ranking over lightweight tuples/objects, and only hydrate the top-K paginated slice (e.g. 50 tickets) as full ORM entities.
  3. Maintain strict parity with golden vectors and existing sorting/tie-break test suites.
- **Verdict**: **APPROVED**.

### Candidate B4: Cache Stale-While-Revalidate (SWR)
- **Empirical Evidence**: A5 showed that Cache-ON provides zero throughput benefit during concurrent write traffic due to frequent cache invalidations causing thundering herd stampedes.
- **Proposed Change**:
  1. Implement Stale-While-Revalidate for time-based cache expiration: if a cache entry is within the stale window (e.g., max 5 seconds), return stale data immediately while a background task refreshes the cache.
  2. Retain strict write-time invalidation on create/assign/status updates to preserve read-your-writes consistency.
  3. Ensure all A7 cache security constraints are fully satisfied.
- **Verdict**: **APPROVED**.

---

## 3. Execution Plan for Part B

All four candidates (B1, B2, B3, B4) are empirically substantiated by the A1–A7 findings. They will be implemented and measured sequentially across concurrency levels (10, 25, 50, 75, 100, 150 clients, 30s x 3 runs, limiter-off) against baseline measurements on both Variant (a) and Variant (b).
