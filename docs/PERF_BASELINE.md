# OpsDesk Performance Baseline & Concurrency Measurements

> **Disclaimer**: These measurements were taken on a single laptop, over loopback interface (`127.0.0.1`), with 1 single uvicorn worker process and an embedded SQLite database in WAL mode (`PRAGMA journal_mode = WAL`, `busy_timeout = 5000ms`, `synchronous = NORMAL`). All metrics depend directly on local machine hardware, CPU frequency scaling, background OS processes, and memory bandwidth. Run-to-run variance is reported below as `(min - max)` across 3 runs of 30 seconds each. **Not a capacity claim** ("system handles N concurrent clients"); all measurements describe what was observed on this machine under this specific configuration.

> **SUPERSEDED NOTICE (Step 2 Goodput & Latency Re-parsing)**: Previous p50 latency measurements at 100+ clients included fast 503 load shedding rejections (e.g. ~2ms responses); re-parsed tables calculate goodput (2xx/s) and latency strictly on 2xx responses. Where 503 rejections were mixed in, 2xx p50 is marked `UNVERIFIED (had fast 503s)`.

---

## 1. Test Environment & Hardware Specification

- **Processor (CPU)**: 13th Gen Intel(R) Core(TM) i7-1355U (10 cores, 12 logical processors, `$env:NUMBER_OF_PROCESSORS=12`)
- **Total Physical Memory (RAM)**: 15.65 GB
- **Operating System**: Microsoft Windows 11 Home Single Language (Build 26100)
- **Python Runtime**: 3.11.9 (64-bit)
- **Server Runtime**: FastAPI 0.139.0 + Uvicorn 0.50.0 + Starlette 1.3.1 + AnyIO 4.14.1 (1 worker process)
- **Database**: SQLite 3 (WAL mode, busy_timeout=5000ms, synchronous=NORMAL)
- **Seed Size**: 5,000 tickets seeded via `backend/seed/seed_data.py`

---

## 2. Definitions & Closed-Loop Methodology

- **Concurrent Client**: A closed-loop virtual worker that sends a request, awaits the response, sleeps for think time $T$ ($T=0$ ms for worst-case closed-loop), and immediately sends the next request.
- **Goodput (2xx/s)**: Count of successful HTTP 2xx responses divided by the total measurement window duration (e.g. 90 seconds for $3 \times 30\text{s}$ repeats). Rejections (429, 503) and timeouts (599) do not contribute to goodput.
- **Latency Accounting**: `2xx p50 (ms)` reflects exclusively the round-trip latency of successful 2xx responses. Where 503 load shedding occurred, the raw response times were dominated by sub-2ms rejection short-circuits; such cells are explicitly annotated as `UNVERIFIED (had fast 503s)` to prevent misleading latency claims.
- **Workload Mix**:
  - `70%`: `GET /api/tickets?view=triage&limit=25`
  - `20%`: `GET /api/tickets/{id}`
  - `5%`: `POST /api/tickets` (with unique `Idempotency-Key` and agency context)
  - `5%`: `POST /api/tickets/{id}/assign` (with agent assignment)
- **Rate Limiter**: Explicitly disabled (`RATE_LIMIT_PER_MINUTE=1000000`) for all capacity runs to isolate raw server throughput from rate limiting.
- **Client-Side Timeout**: 30.0 seconds. Status `599` represents client-side request timeout / connection error.

---

## 3. Historic Pre-Diagnosis Measurements (Reference)

Historic runs conducted prior to M5 collapse diagnosis across 25, 100, and 250 concurrent clients:

### Prior Unoptimized Baseline
| Concurrent Clients | Median RPS | p50 (ms) | p95 (ms) | p99 (ms) | Statuses | DB Locked Errors |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **25** | 38.7 (38.7 - 41.5) | 860.5 (800.7 - 868.0) | 1016.6 (941.2 - 1016.6) | 1047.8 (978.4 - 1047.8) | `{200: 3453, 201: 172}` | 0 |
| **100** | 3.6 (3.4 - 3.6) | 30091.7 (30030.1 - 30128.7) | 30164.2 (30124.8 - 30198.5) | 30172.0 (30141.2 - 30206.1) | `{200: 21, 599: 300}` | 0 |
| **250** | 8.2 (8.2 - 8.2) | 30248.4 (30209.6 - 30263.1) | 30376.1 (30348.9 - 30397.6) | 30397.6 (30374.0 - 30420.8) | `{200: 1, 599: 750}` | 0 |

### Prior Simple Cache (Failing at 100 and 250 Clients)
| Concurrent Clients | Median RPS | p50 (ms) | p95 (ms) | p99 (ms) | Statuses | DB Locked Errors |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **25** | 98.2 (97.6 - 106.3) | 17.5 (17.0 - 21.0) | 1200.4 (1125.6 - 1318.4) | 1358.3 (1258.3 - 1736.2) | `{200: 8718, 201: 445, 409: 1}` | 0 |
| **100** | 2.2 (2.2 - 2.3) | 37320.5 (36727.3 - 37933.4) | 44199.7 (43673.2 - 45301.1) | 44789.3 (44301.7 - 45943.5) | `{200: 7, 599: 300}` | 0 |
| **250** | 1.7 (0.4 - 2.8) | 91655.1 (52795.2 - 119654.6) | 103180.9 (65988.9 - 132455.4) | 104292.7 (67127.6 - 133188.6) | `{200: 62, 599: 358, 201: 4}` | 0 |

---

## 3.1. Deadlock & Nested DB Checkout Audit (Empirical Rejection)

During M5 diagnosis, a key hypothesis considered was whether individual request handlers performed nested SQLAlchemy database connection checkouts (e.g. checking out connection 1 for an outer transaction and checking out connection 2 for an audit log or helper within the same request thread), which under a pool size of $N$ can produce self-deadlock.

### Static Codebase Audit
Static grep across `backend/app` and `backend/services` confirmed that:
1. Every route handler receives its database session strictly via FastAPI dependency injection: `db: Session = Depends(get_db)`.
2. No route handler, middleware, or service instantiates secondary `SessionLocal()` sessions during request servicing.
3. Database connections are checked out once per request on entry and returned cleanly upon request exit.

### Deterministic Pool Exhaustion Test
To empirically verify the nested checkout hypothesis, a deterministic deadlock test was run (`scripts/diag/test_deterministic_deadlock.py`) with intentionally constrained pool capacity:
- `DB_POOL_SIZE = 1`
- `DB_MAX_OVERFLOW = 0`
- `DB_POOL_TIMEOUT = 3.0s`

Under this configuration, any nested checkout within a single request is guaranteed to hang for 3 seconds and trigger a `QueuePool` timeout.

**Test Results Across All 13 Core Endpoints**:
| Endpoint | Method | Status | Duration (ms) | Result |
| :--- | :--- | :--- | :--- | :--- |
| `/health` | GET | 200 | 12.1 ms | Pass (No nested checkout) |
| `/ready` | GET | 200 | 15.4 ms | Pass (No nested checkout) |
| `/api/tickets?view=triage&limit=25` | GET | 200 | 28.3 ms | Pass (No nested checkout) |
| `/api/tickets?view=urgent` | GET | 200 | 22.0 ms | Pass (No nested checkout) |
| `/api/tickets/{id}` | GET | 200 | 16.8 ms | Pass (No nested checkout) |
| `/api/tickets` | POST | 201 | 35.6 ms | Pass (No nested checkout) |
| `/api/tickets/{id}/assign` | POST | 200 | 41.2 ms | Pass (No nested checkout) |
| `/api/tickets/{id}/unassign` | POST | 200 | 38.7 ms | Pass (No nested checkout) |
| `/api/tickets/{id}/status` | PATCH | 200 | 39.5 ms | Pass (No nested checkout) |
| `/api/tickets/{id}/escalate` | POST | 200 | 44.1 ms | Pass (No nested checkout) |
| `/api/tickets/{id}/transfer` | POST | 200 | 51.8 ms | Pass (No nested checkout) |
| `/api/insights/themes` | GET | 200 | 26.4 ms | Pass (No nested checkout) |
| `/api/export/tickets.csv` | GET | 200 | 48.9 ms | Pass (No nested checkout) |

**Conclusion**: **Nested checkout NAHI mila (hypothesis rejected)**. All 13 endpoints completed in under 52 ms with zero pool timeouts. The observed baseline collapse was driven strictly by concurrency starvation in the QueuePool under unprojected ORM hydration and thread pool saturation, not nested checkouts.

---

## 4. Part B Step-by-Step Measured Progression (Exact Raw Runs)

Each stage below was benchmarked across concurrency levels 10, 25, 50, 75, 100, 150 closed-loop clients ($T=0$), 30 seconds $\times$ 3 repeats per level, with rate limiter OFF, on a fresh server and isolated temp database. Metrics were re-parsed strictly on 2xx responses (Step 2 Goodput Methodology).

### 4.1. Baseline (Pre-Fix, Part A State)
*Source: `docs/perf_runs/B0_baseline.txt` and `docs/perf_runs/step2_goodput_reparsed.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 8873 | 8872 | 98.6 2xx/s | 0.0% | 0.0% | 0/1 | 14.6 (13.5 - 16.5) | 14.6 (13.5 - 16.5) |
| **25** | 8266 | 8266 | 91.8 2xx/s | 0.0% | 0.0% | 0/0 | 23.3 (20.6 - 23.6) | 23.3 (20.6 - 23.6) |
| **50** | 5064 | 5063 | 56.3 2xx/s | 0.0% | 0.0% | 0/1 | 406.8 (382.7 - 418.4) | 406.8 (382.7 - 418.4) |
| **75** | 3580 | 3580 | 39.8 2xx/s | 0.0% | 0.0% | 0/0 | 1007.5 (976.8 - 1061.7) | 1007.5 (976.8 - 1061.7) |
| **100** | 328 | 28 | 0.3 2xx/s | 0.0% | 91.5% | 0/0 | 35768.9 (35717.1 - 36321.3) | 35768.9 (35717.1 - 36321.3) |
| **150** | 470 | 20 | 0.2 2xx/s | 0.0% | 95.7% | 0/0 | 40556.4 (39904.7 - 41645.0) | 40556.4 (39904.7 - 41645.0) |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 370 | 370 | 4.1 2xx/s | 0.0% | 0.0% | 0/0 | 3099.4 (3009.0 - 3181.0) | 3099.4 (3009.0 - 3181.0) |
| **25** | 338 | 338 | 3.8 2xx/s | 0.0% | 0.0% | 0/0 | 8760.2 (8445.8 - 9043.2) | 8760.2 (8445.8 - 9043.2) |
| **50** | 366 | 365 | 4.1 2xx/s | 0.0% | 0.3% | 0/0 | 14132.0 (13064.9 - 14590.8) | 14132.0 (13064.9 - 14590.8) |
| **75** | 562 | 562 | 6.2 2xx/s | 0.0% | 0.0% | 0/0 | 11929.3 (11281.7 - 12861.1) | 11929.3 (11281.7 - 12861.1) |
| **100** | 323 | 26 | 0.3 2xx/s | 0.0% | 92.0% | 0/0 | 36161.4 (36032.5 - 36564.3) | 36161.4 (36032.5 - 36564.3) |
| **150** | 451 | 1 | 0.0 2xx/s | 0.0% | 99.8% | 0/0 | 42008.6 (41833.5 - 42764.3) | 42008.6 (41833.5 - 42764.3) |

---

### 4.2. After B1 (QueuePool Optimization + Timeout Handler)
*Changes: `DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=20`, `DB_POOL_TIMEOUT=5`, exception handler returning 503 with `Retry-After: 5` on `SQLAlchemyTimeoutError`.*  
*Source: `docs/perf_runs/B1_pool.txt` and `docs/perf_runs/step2_goodput_reparsed.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 10747 | 10747 | 119.4 2xx/s | 0.0% | 0.0% | 0/0 | 12.0 (10.4 - 13.3) | 12.0 (10.4 - 13.3) |
| **25** | 7822 | 7821 | 86.9 2xx/s | 0.0% | 0.0% | 0/1 | 20.0 (19.7 - 28.6) | 20.0 (19.7 - 28.6) |
| **50** | 4064 | 4063 | 45.1 2xx/s | 0.0% | 0.0% | 0/1 | 245.8 (209.6 - 262.3) | 245.8 (209.6 - 262.3) |
| **75** | 3590 | 3590 | 39.9 2xx/s | 0.0% | 0.0% | 0/0 | 726.3 (606.2 - 1183.4) | 726.3 (606.2 - 1183.4) |
| **100** | 2437 | 2360 | 26.2 2xx/s | 3.0% | 0.0% | 0/3 | UNVERIFIED (had fast 503s) | 1325.9 (1221.3 - 1346.6) |
| **150** | 468 | 263 | 2.9 2xx/s | 43.8% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 19009.9 (18092.7 - 19252.4) |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 386 | 386 | 4.3 2xx/s | 0.0% | 0.0% | 0/0 | 3108.2 (2990.3 - 3167.2) | 3108.2 (2990.3 - 3167.2) |
| **25** | 341 | 341 | 3.8 2xx/s | 0.0% | 0.0% | 0/0 | 8609.9 (8114.4 - 9097.4) | 8609.9 (8114.4 - 9097.4) |
| **50** | 355 | 345 | 3.8 2xx/s | 0.0% | 2.8% | 0/0 | 17537.7 (17481.8 - 18340.4) | 17537.7 (17481.8 - 18340.4) |
| **75** | 419 | 356 | 4.0 2xx/s | 14.8% | 0.2% | 0/0 | UNVERIFIED (had fast 503s) | 18447.6 (18429.8 - 21423.9) |
| **100** | 663 | 596 | 6.6 2xx/s | 8.6% | 1.4% | 0/1 | UNVERIFIED (had fast 503s) | 14817.5 (13078.4 - 17690.1) |
| **150** | 470 | 287 | 3.2 2xx/s | 38.1% | 0.0% | 0/2 | UNVERIFIED (had fast 503s) | 19953.2 (18446.9 - 24253.2) |

---

### 4.3. After B2 (In-Flight Concurrency Limiter & 503 Load Shedding)
*Changes: Global in-flight semaphore (`MAX_CONCURRENT_REQUESTS=60`, `MAX_QUEUE_WAIT_TIMEOUT_SEC=2.0s`), shedding excess queued requests with 503 `Retry-After: 2`, with `/health` and `/ready` strictly exempt.*  
*Source: `docs/perf_runs/B2_shedding.txt` and `docs/perf_runs/step2_goodput_reparsed.txt`*

> **Critical Evaluation & Default-Off Decision**:
> While B2 successfully prevented timeouts in Variant (a) by shedding excess requests, on Variant (b) at 100 concurrent clients it caused an acute **goodput regression**: successful 2xx responses fell from 596 down to 242, because 72.4% of valid requests were rejected with 503 after waiting 2.0s in the in-memory semaphore queue. Because in-memory request-level queuing throttles requests before SQLite database serialization is reached, B2 has been configured as **default-off** (`CONCURRENCY_LOAD_SHEDDING_ENABLED=false`) in `backend/app/main.py`.

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 10826 | 10826 | 120.3 2xx/s | 0.0% | 0.0% | 0/0 | 11.8 (11.0 - 12.6) | 11.8 (11.0 - 12.6) |
| **25** | 8122 | 8122 | 90.2 2xx/s | 0.0% | 0.0% | 0/0 | 20.3 (19.5 - 33.4) | 20.3 (19.5 - 33.4) |
| **50** | 4519 | 4518 | 50.2 2xx/s | 0.0% | 0.0% | 0/1 | 191.5 (185.5 - 220.7) | 191.5 (185.5 - 220.7) |
| **75** | 2974 | 2972 | 33.0 2xx/s | 0.0% | 0.0% | 0/2 | 1147.6 (1018.9 - 1154.6) | 1147.6 (1018.9 - 1154.6) |
| **100** | 2103 | 2102 | 23.4 2xx/s | 0.0% | 0.0% | 0/1 | 1875.6 (1820.8 - 2067.1) | 1875.6 (1820.8 - 2067.1) |
| **150** | 1426 | 1426 | 15.8 2xx/s | 0.0% | 0.0% | 0/0 | 2653.3 (2248.6 - 2674.6) | 2653.3 (2248.6 - 2674.6) |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 357 | 357 | 4.0 2xx/s | 0.0% | 0.0% | 0/0 | 3453.3 (3362.6 - 3468.5) | 3453.3 (3362.6 - 3468.5) |
| **25** | 336 | 336 | 3.7 2xx/s | 0.0% | 0.0% | 0/0 | 9637.8 (9495.0 - 9743.9) | 9637.8 (9495.0 - 9743.9) |
| **50** | 364 | 364 | 4.0 2xx/s | 0.0% | 0.0% | 0/0 | 16207.4 (15787.7 - 16749.7) | 16207.4 (15787.7 - 16749.7) |
| **75** | 643 | 367 | 4.1 2xx/s | 41.2% | 1.7% | 0/0 | UNVERIFIED (had fast 503s) | 8556.5 (7164.7 - 12513.5) |
| **100** | 877 | 242 | 2.7 2xx/s | 72.4% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 2046.8 (2030.6 - 2056.0) |
| **150** | 928 | 208 | 2.3 2xx/s | 77.6% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 2098.6 (2089.6 - 6382.8) |

---

### 4.4. After B3 (Triage Query Projection & Top-K Slicing)
*Changes: `GET /api/tickets?view=triage` scoring queries only 7 projection columns via `with_entities` (`id`, `priority`, `check_in_date`, `lcd_date`, `intent`, `created_at`, `status`), scores in memory, and only loads full ORM Ticket objects for the top-50 paginated slice.*  
*Source: `docs/perf_runs/B3_triage.txt` and `docs/perf_runs/step2_goodput_reparsed.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 11801 | 11801 | 131.1 2xx/s | 0.0% | 0.0% | 0/0 | 18.4 (16.4 - 20.4) | 18.4 (16.4 - 20.4) |
| **25** | 8659 | 8658 | 96.2 2xx/s | 0.0% | 0.0% | 0/1 | 41.2 (30.6 - 46.8) | 41.2 (30.6 - 46.8) |
| **50** | 5606 | 5606 | 62.3 2xx/s | 0.0% | 0.0% | 0/0 | 212.3 (202.4 - 215.8) | 212.3 (202.4 - 215.8) |
| **75** | 3935 | 3934 | 43.7 2xx/s | 0.0% | 0.0% | 0/1 | 666.6 (643.0 - 674.1) | 666.6 (643.0 - 674.1) |
| **100** | 3466 | 3466 | 38.5 2xx/s | 0.0% | 0.0% | 0/0 | 986.9 (809.9 - 1220.3) | 986.9 (809.9 - 1220.3) |
| **150** | 1602 | 1602 | 17.8 2xx/s | 0.0% | 0.0% | 0/0 | 2003.1 (1979.8 - 2293.7) | 2003.1 (1979.8 - 2293.7) |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 1565 | 1565 | 17.4 2xx/s | 0.0% | 0.0% | 0/0 | 10.2 (9.1 - 10.6) | 10.2 (9.1 - 10.6) |
| **25** | 548 | 548 | 6.1 2xx/s | 0.0% | 0.0% | 0/0 | 5298.9 (5079.2 - 5356.8) | 5298.9 (5079.2 - 5356.8) |
| **50** | 644 | 644 | 7.2 2xx/s | 0.0% | 0.0% | 0/0 | 7346.0 (7309.7 - 8960.5) | 7346.0 (7309.7 - 8960.5) |
| **75** | 797 | 546 | 6.1 2xx/s | 31.4% | 0.0% | 0/1 | UNVERIFIED (had fast 503s) | 8672.0 (8469.9 - 9993.3) |
| **100** | 1071 | 416 | 4.6 2xx/s | 61.2% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 2058.7 (2044.0 - 2069.2) |
| **150** | 932 | 274 | 3.0 2xx/s | 70.6% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 4164.4 (2474.1 - 6407.7) |

---

### 4.5. After B4 (Stale-While-Revalidate SWR + Write Invalidation)
*Changes: SWR with 2.0s fresh TTL and 5.0s max stale window (`TRIAGE_CACHE_MAX_STALE_SEC=5.0`), triggering single-flight asynchronous background refresh on stale hit while immediately purging cache on mutating writes (`create`, `assign`, `status`, `escalate`, `transfer`) to maintain strict read-your-writes consistency.*  
*Source: `docs/perf_runs/B4_cache_swr.txt` and `docs/perf_runs/step2_goodput_reparsed.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 11733 | 11732 | 130.4 2xx/s | 0.0% | 0.0% | 0/1 | 19.0 (16.9 - 21.6) | 19.0 (16.9 - 21.6) |
| **25** | 8484 | 8482 | 94.2 2xx/s | 0.0% | 0.0% | 0/2 | 40.8 (38.4 - 62.9) | 40.8 (38.4 - 62.9) |
| **50** | 5909 | 5908 | 65.6 2xx/s | 0.0% | 0.0% | 0/1 | 204.4 (198.0 - 210.8) | 204.4 (198.0 - 210.8) |
| **75** | 4048 | 4048 | 45.0 2xx/s | 0.0% | 0.0% | 0/0 | 647.2 (632.2 - 725.2) | 647.2 (632.2 - 725.2) |
| **100** | 3793 | 3793 | 42.1 2xx/s | 0.0% | 0.0% | 0/0 | 999.6 (835.2 - 1041.2) | 999.6 (835.2 - 1041.2) |
| **150** | 1443 | 1443 | 16.0 2xx/s | 0.0% | 0.0% | 0/0 | 2156.0 (1765.0 - 2214.3) | 2156.0 (1765.0 - 2214.3) |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Total Reqs | 2xx Count | Goodput (2xx/s) | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms) | All p50 (incl. 503s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 2138 | 2138 | 23.8 2xx/s | 0.0% | 0.0% | 0/0 | 9.9 (9.6 - 11.0) | 9.9 (9.6 - 11.0) |
| **25** | 1278 | 1278 | 14.2 2xx/s | 0.0% | 0.0% | 0/0 | 25.8 (22.4 - 32.0) | 25.8 (22.4 - 32.0) |
| **50** | 661 | 657 | 7.3 2xx/s | 0.6% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 7238.4 (4947.8 - 9209.0) |
| **75** | 939 | 690 | 7.7 2xx/s | 26.5% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 6128.0 (6120.4 - 6475.9) |
| **100** | 1154 | 463 | 5.1 2xx/s | 59.9% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 2035.8 (2035.4 - 2104.8) |
| **150** | 759 | 219 | 2.4 2xx/s | 71.1% | 0.0% | 0/0 | UNVERIFIED (had fast 503s) | 6204.0 (5528.0 - 7011.0) |

---

## 5. 90-Second Time-Series Comparison: Baseline vs Optimized HEAD

To verify systemic stability over a sustained window, a 90-second continuous closed-loop load test (100 concurrent clients) was executed on both the pre-fix Baseline (`98ce890`) and the optimized HEAD (`788bb9a`) using the active connection pool logger (`scripts/diag/instrument_pool.py`).

### Baseline (`98ce890`)
- **Total Requests Attempted**: 202
- **Successful 2xx Responses**: 2
- **Client Timeouts (599)**: 200 (99.0% timeout rate)
- **Effective Goodput**: 0.02 2xx/s
- **Pool State**: `Pool_CheckedOut` pegged at exactly 30 connections from second 3 through second 90 without ever releasing back to the pool, stalling all worker threads.
- *Data file*: `docs/perf_runs/step1d_timeseries_baseline.csv`

### Optimized HEAD (`788bb9a`)
- **Total Requests Attempted**: 9,164
- **Successful 2xx Responses**: 9,164 (100% success rate)
- **Client Timeouts (599)**: 0
- **Load Shed Rejections (503)**: 0
- **Effective Goodput**: 101.82 2xx/s
- **Pool State**: `Pool_CheckedOut` fluctuated dynamically between 42 and 50 checkouts with rapid turnover, maintaining constant throughput and zero thread starvation.
- *Data file*: `docs/perf_runs/step1d_timeseries_head.csv`
