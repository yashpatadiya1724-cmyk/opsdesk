# OpsDesk Performance Baseline & Concurrency Measurements

> **Disclaimer**: These measurements were taken on a single laptop, over loopback interface (`127.0.0.1`), with 1 single uvicorn worker process and an embedded SQLite database in WAL mode (`PRAGMA journal_mode = WAL`, `busy_timeout = 5000ms`, `synchronous = NORMAL`). All metrics depend directly on local machine hardware, CPU frequency scaling, background OS processes, and memory bandwidth. Run-to-run variance is reported below as `(min - max)` across 3 runs of 30 seconds each. **Not a capacity claim** ("system handles N concurrent clients"); all measurements describe what was observed on this machine under this specific configuration.

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
- **Workload Mix**:
  - `70%`: `GET /api/tickets?view=triage&limit=25`
  - `20%`: `GET /api/tickets/{id}`
  - `5%`: `POST /api/tickets` (with unique `Idempotency-Key` and agency context)
  - `5%`: `POST /api/tickets/{id}/assign` (with agent assignment)
- **Rate Limiter**: Explicitly disabled (`RATE_LIMIT_PER_MINUTE=1000000`) for all capacity runs to isolate raw server throughput from rate limiting.
- **Client-Side Timeout**: 30.0 seconds. Status `599` represents client-side request timeout / connection error.
- **Observed Collapse & Cause**:
  - On a single laptop, loopback, 1 process, SQLite, closed-loop clients, limiter off:
  - Collapse was observed at 100 concurrent clients (p50 > 35,000 ms, 300 timeouts out of 300-328 requests).
  - **Observed Cause**:
    1. **QueuePool Checkout Starvation**: SQLAlchemy QueuePool was configured with `pool_size=10` and `max_overflow=20` (30 connections total), while AnyIO default threadpool ran with 40 tokens. All 30 connections became saturated, and excess worker threads blocked inside `_do_get` waiting on a 30s `pool_timeout`, forcing requests into client 30s timeouts (`599`).
    2. **ORM Hydration Bottleneck**: In triage queries with 5,000 unassigned tickets, 64.3% (53.60 ms out of 83.38 ms) was spent purely in SQLAlchemy ORM object instantiation (`loading.py:1075(_instance)` and `_populate_full`) instantiating 5,000 full `Ticket` instances.
    3. **Thundering Herd on Writes**: 10% mutating writes continuously invalidated the triage cache, triggering stampedes of uncached 5,000-row ORM queries.

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

## 4. Part B Step-by-Step Measured Progression (Exact Raw Runs)

Each stage below was benchmarked across concurrency levels 10, 25, 50, 75, 100, 150 closed-loop clients ($T=0$), 30 seconds $\times$ 3 repeats per level, with rate limiter OFF, on a fresh server and isolated temp database.

### 4.1. Baseline (Pre-Fix, Part A State)
*Source: `docs/perf_runs/B0_baseline.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 98.6 (94.8 - 101.2) | 14.6 (13.5 - 16.5) | 555.0 (545.9 - 617.8) | 779.7 (727.8 - 805.6) | `{"200": 8447, "201": 425, "409": 1}` |
| 25 | 90.7 (90.3 - 91.1) | 23.3 (20.6 - 23.6) | 1220.4 (1167.7 - 1270.8) | 1463.4 (1348.6 - 1481.3) | `{"200": 7840, "201": 426}` |
| 50 | 54.3 (53.5 - 56.9) | 406.8 (382.7 - 418.4) | 1762.8 (1638.5 - 1843.3) | 6185.0 (5963.8 - 6203.5) | `{"200": 4827, "201": 236, "409": 1}` |
| 75 | 38.1 (37.8 - 38.6) | 1007.5 (976.8 - 1061.7) | 3330.0 (3215.6 - 3456.9) | 11171.7 (11046.5 - 11732.5) | `{"200": 3402, "201": 178}` |
| 100 | 2.4 (2.3 - 2.4) | 35768.9 (35717.1 - 36321.3) | 43333.3 (43275.5 - 45284.0) | 43998.2 (43928.3 - 46075.6) | `{"200": 28, "599": 300}` |
| 150 | 2.9 (2.8 - 3.0) | 40556.4 (39904.7 - 41645.0) | 51566.7 (51006.7 - 52215.4) | 52990.3 (52716.6 - 53170.7) | `{"200": 20, "599": 450}` |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 4.0 (3.9 - 4.0) | 3099.4 (3009.0 - 3181.0) | 3686.2 (3480.5 - 3687.0) | 3938.9 (3770.7 - 4292.4) | `{"200": 360, "201": 10}` |
| 25 | 3.3 (3.2 - 3.3) | 8760.2 (8445.8 - 9043.2) | 10489.5 (10347.2 - 11400.8) | 11671.1 (11656.1 - 12029.1) | `{"200": 323, "201": 15}` |
| 50 | 2.7 (2.6 - 2.9) | 14132.0 (13064.9 - 14590.8) | 22561.7 (20638.9 - 22773.5) | 23538.5 (22581.7 - 25129.3) | `{"200": 347, "201": 18, "599": 1}` |
| 75 | 4.1 (3.8 - 4.4) | 11929.3 (11281.7 - 12861.1) | 20772.6 (20462.1 - 21099.4) | 24275.3 (21666.4 - 25646.2) | `{"200": 544, "201": 18}` |
| 100 | 2.2 (2.2 - 2.2) | 36161.4 (36032.5 - 36564.3) | 44188.6 (43923.0 - 44305.0) | 44828.9 (44557.1 - 45025.3) | `{"200": 26, "599": 297}` |
| 150 | 2.8 (2.7 - 2.8) | 42008.6 (41833.5 - 42764.3) | 52689.4 (52536.6 - 53204.2) | 53663.4 (53480.0 - 54125.0) | `{"200": 1, "599": 450}` |

---

### 4.2. After B1 (QueuePool Optimization + Timeout Handler)
*Changes: `DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=20`, `DB_POOL_TIMEOUT=5`, exception handler returning 503 with `Retry-After: 5` on `SQLAlchemyTimeoutError`.*  
*Source: `docs/perf_runs/B1_pool.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 116.9 (115.9 - 123.7) | 12.0 (10.4 - 13.3) | 467.2 (461.5 - 468.4) | 579.2 (573.5 - 612.4) | `{"200": 10158, "201": 589}` |
| 25 | 86.8 (83.4 - 87.3) | 20.0 (19.7 - 28.6) | 1355.1 (1177.0 - 1355.7) | 1559.9 (1316.1 - 1574.7) | `{"200": 7422, "201": 399, "409": 1}` |
| 50 | 44.0 (41.6 - 45.6) | 245.8 (209.6 - 262.3) | 2275.1 (2252.8 - 2542.6) | 7204.2 (7102.0 - 7645.6) | `{"200": 3879, "201": 184, "409": 1}` |
| 75 | 39.5 (29.7 - 45.9) | 726.3 (606.2 - 1183.4) | 3743.6 (2449.6 - 6310.7) | 11739.2 (10620.5 - 12940.4) | `{"200": 3414, "201": 176}` |
| 100 | 23.9 (22.3 - 31.0) | 1325.9 (1221.3 - 1346.6) | 16157.0 (9017.9 - 16240.0) | 19912.3 (15623.1 - 20449.7) | `{"200": 2235, "201": 125, "409": 3, "503": 74}` |
| 150 | 4.2 (4.1 - 4.2) | 19009.9 (18092.7 - 19252.4) | 33740.6 (33337.0 - 34697.5) | 34868.1 (34675.2 - 35939.0) | `{"200": 241, "201": 22, "503": 205}` |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 3.9 (3.9 - 4.4) | 3108.2 (2990.3 - 3167.2) | 3720.7 (3596.7 - 3847.8) | 4195.4 (3958.2 - 4601.3) | `{"200": 372, "201": 14}` |
| 25 | 3.3 (3.1 - 3.4) | 8609.9 (8114.4 - 9097.4) | 10631.4 (10246.9 - 10660.7) | 11890.0 (11551.7 - 12384.0) | `{"200": 314, "201": 27}` |
| 50 | 2.6 (2.4 - 2.8) | 17537.7 (17481.8 - 18340.4) | 27936.8 (27140.3 - 30005.3) | 29643.8 (29632.0 - 30018.7) | `{"200": 328, "201": 17, "599": 10}` |
| 75 | 2.9 (2.7 - 3.1) | 18447.6 (18429.8 - 21423.9) | 27405.6 (25327.9 - 28217.3) | 29805.2 (27093.6 - 31308.7) | `{"200": 340, "201": 16, "503": 62, "599": 1}` |
| 100 | 4.2 (3.6 - 4.6) | 14817.5 (13078.4 - 17690.1) | 26327.6 (25425.3 - 28846.4) | 29283.7 (26596.1 - 30009.0) | `{"200": 564, "201": 32, "409": 1, "503": 57, "599": 9}` |
| 150 | 3.1 (3.0 - 3.9) | 19953.2 (18446.9 - 24253.2) | 41102.9 (29487.5 - 43047.3) | 44124.5 (31198.5 - 44455.7) | `{"200": 264, "201": 23, "409": 2, "503": 179}` |

---

### 4.3. After B2 (In-Flight Concurrency Limiter & 503 Load Shedding)
*Changes: Global in-flight semaphore (`MAX_CONCURRENT_REQUESTS=60`, `MAX_QUEUE_WAIT_TIMEOUT_SEC=2.0s`), shedding excess queued requests with 503 `Retry-After: 2`, with `/health` and `/ready` strictly exempt.*  
*Source: `docs/perf_runs/B2_shedding.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 119.0 (117.2 - 123.2) | 11.8 (11.0 - 12.6) | 473.4 (467.1 - 486.6) | 607.8 (584.4 - 638.3) | `{"200": 10272, "201": 554}` |
| 25 | 90.8 (85.0 - 91.3) | 20.3 (19.5 - 33.4) | 1295.8 (1101.7 - 1349.7) | 1576.6 (1300.4 - 1583.5) | `{"200": 7715, "201": 407}` |
| 50 | 48.9 (47.2 - 50.5) | 191.5 (185.5 - 220.7) | 2188.0 (2101.3 - 2351.3) | 6623.7 (6396.5 - 6823.9) | `{"200": 4282, "201": 236, "409": 1}` |
| 75 | 31.8 (29.9 - 33.6) | 1147.6 (1018.9 - 1154.6) | 5819.4 (5388.4 - 6483.5) | 12842.6 (12547.7 - 13227.1) | `{"200": 2819, "201": 153, "409": 2}` |
| 100 | 21.6 (21.5 - 22.6) | 1875.6 (1820.8 - 2067.1) | 12856.0 (12827.5 - 13285.4) | 17911.3 (17697.5 - 18233.8) | `{"200": 1994, "201": 108, "409": 1}` |
| 150 | 14.7 (14.7 - 14.9) | 2653.3 (2248.6 - 2674.6) | 21864.5 (21216.0 - 21944.1) | 24654.9 (24195.0 - 24836.8) | `{"200": 1338, "201": 88}` |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 3.7 (3.7 - 3.9) | 3453.3 (3362.6 - 3468.5) | 3990.4 (3917.1 - 4100.9) | 4212.7 (4166.5 - 4784.3) | `{"200": 341, "201": 16}` |
| 25 | 3.1 (2.9 - 3.3) | 9637.8 (9495.0 - 9743.9) | 12393.7 (12173.9 - 13166.1) | 13928.0 (13787.9 - 14334.7) | `{"200": 316, "201": 20}` |
| 50 | 2.8 (2.7 - 3.1) | 16207.4 (15787.7 - 16749.7) | 24256.3 (22859.3 - 24885.7) | 25983.4 (24835.6 - 26291.3) | `{"200": 343, "201": 21}` |
| 75 | 4.3 (4.2 - 4.3) | 8556.5 (7164.7 - 12513.5) | 28250.9 (27693.9 - 29724.3) | 30020.1 (29214.4 - 32910.7) | `{"200": 345, "201": 22, "503": 265, "599": 11}` |
| 100 | 6.5 (6.0 - 7.9) | 2046.8 (2030.6 - 2056.0) | 29899.3 (29773.2 - 33122.2) | 34603.3 (32561.9 - 36605.2) | `{"200": 231, "201": 11, "503": 635}` |
| 150 | 7.6 (5.6 - 7.9) | 2098.6 (2089.6 - 6382.8) | 35330.2 (33246.4 - 36126.9) | 38184.6 (35903.4 - 39412.5) | `{"200": 201, "201": 7, "503": 720}` |

---

### 4.4. After B3 (Triage Query Projection & Top-K Slicing)
*Changes: Triage scoring queries only 7 projection columns via `with_entities` (`id`, `priority`, `check_in_date`, `lcd_date`, `intent`, `created_at`, `status`), scores in memory, and only loads full ORM Ticket objects for the top-50 paginated slice.*  
*Source: `docs/perf_runs/B3_triage.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 131.6 (127.8 - 133.0) | 18.4 (16.4 - 20.4) | 340.8 (336.2 - 346.8) | 454.8 (448.7 - 474.6) | `{"200": 11222, "201": 579}` |
| 25 | 93.6 (93.4 - 99.2) | 41.2 (30.6 - 46.8) | 946.0 (901.4 - 1000.1) | 1142.3 (1031.3 - 1198.0) | `{"200": 8231, "201": 427, "409": 1}` |
| 50 | 61.2 (60.4 - 61.7) | 212.3 (202.4 - 215.8) | 1687.8 (1677.3 - 1706.3) | 5788.0 (5702.1 - 5849.7) | `{"200": 5313, "201": 293}` |
| 75 | 43.4 (40.4 - 43.5) | 666.6 (643.0 - 674.1) | 2674.1 (2458.2 - 3799.6) | 11868.2 (11607.7 - 11969.6) | `{"200": 3767, "201": 167, "409": 1}` |
| 100 | 37.3 (30.5 - 43.6) | 986.9 (809.9 - 1220.3) | 7919.3 (6514.0 - 10628.5) | 15450.9 (14969.8 - 16978.7) | `{"200": 3295, "201": 171}` |
| 150 | 16.5 (16.0 - 17.7) | 2003.1 (1979.8 - 2293.7) | 21067.6 (20866.2 - 21439.6) | 24681.4 (24555.5 - 24991.4) | `{"200": 1517, "201": 85}` |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 15.6 (14.4 - 20.9) | 10.2 (9.1 - 10.6) | 2143.8 (2141.5 - 2236.7) | 2529.1 (2352.5 - 2715.0) | `{"200": 1485, "201": 80}` |
| 25 | 5.6 (5.4 - 6.0) | 5298.9 (5079.2 - 5356.8) | 6325.0 (5936.9 - 6657.4) | 8468.3 (8274.9 - 8562.0) | `{"200": 520, "201": 28}` |
| 50 | 6.2 (4.9 - 6.2) | 7346.0 (7309.7 - 8960.5) | 12451.4 (11929.6 - 15719.4) | 13648.2 (13284.8 - 17119.0) | `{"200": 619, "201": 25}` |
| 75 | 7.1 (6.6 - 7.2) | 8672.0 (8469.9 - 9993.3) | 16960.0 (16611.0 - 17073.5) | 18807.5 (18423.2 - 18844.4) | `{"200": 513, "201": 33, "409": 1, "503": 250}` |
| 100 | 9.3 (8.4 - 9.4) | 2058.7 (2044.0 - 2069.2) | 22668.5 (22622.8 - 22915.5) | 24797.0 (24193.6 - 25349.6) | `{"200": 398, "201": 18, "503": 655}` |
| 150 | 9.0 (7.0 - 9.5) | 4164.4 (2474.1 - 6407.7) | 28064.4 (27880.2 - 30571.4) | 30333.6 (29823.3 - 33461.8) | `{"200": 265, "201": 9, "503": 658}` |

---

### 4.5. After B4 (Stale-While-Revalidate SWR + Write Invalidation)
*Changes: SWR with 2.0s fresh TTL and 5.0s max stale window (`TRIAGE_CACHE_MAX_STALE_SEC=5.0`), triggering single-flight asynchronous background refresh on stale hit while immediately purging cache on mutating writes (`create`, `assign`, `status`, `escalate`, `transfer`) to maintain strict read-your-writes consistency.*  
*Source: `docs/perf_runs/B4_cache_swr.txt`*

#### Variant (a) [normal seed, ~456 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 129.3 (127.1 - 133.8) | 19.0 (16.9 - 21.6) | 336.9 (336.7 - 349.3) | 432.1 (429.1 - 484.8) | `{"200": 11132, "201": 600, "409": 1}` |
| 25 | 92.5 (92.3 - 95.9) | 40.8 (38.4 - 62.9) | 972.4 (838.2 - 1007.8) | 1151.5 (1001.1 - 1255.5) | `{"200": 8060, "201": 422, "409": 2}` |
| 50 | 64.2 (63.6 - 65.2) | 204.4 (198.0 - 210.8) | 1620.0 (1606.4 - 1678.6) | 5442.3 (5357.4 - 5640.6) | `{"200": 5619, "201": 289, "409": 1}` |
| 75 | 43.7 (42.9 - 43.9) | 647.2 (632.2 - 725.2) | 2488.2 (2477.1 - 2787.2) | 11571.9 (11502.5 - 11756.9) | `{"200": 3858, "201": 190}` |
| 100 | 40.7 (38.1 - 43.4) | 999.6 (835.2 - 1041.2) | 7218.7 (6516.7 - 7344.7) | 14950.8 (14688.3 - 14971.8) | `{"200": 3619, "201": 174}` |
| 150 | 16.0 (12.4 - 17.1) | 2156.0 (1765.0 - 2214.3) | 21936.7 (20942.6 - 23535.0) | 25171.8 (24157.0 - 26903.4) | `{"200": 1377, "201": 66}` |

#### Variant (b) [triage-heavy, 5,000 unassigned tickets]
| Clients | Throughput RPS | p50 (ms) | p95 (ms) | p99 (ms) | Combined Statuses |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10 | 22.4 (22.1 - 22.6) | 9.9 (9.6 - 11.0) | 3792.3 (3665.7 - 3962.8) | 4164.0 (4087.2 - 4587.2) | `{"200": 2023, "201": 115}` |
| 25 | 12.4 (12.2 - 12.5) | 25.8 (22.4 - 32.0) | 8649.7 (8525.1 - 8986.4) | 9270.0 (8985.2 - 9725.7) | `{"200": 1239, "201": 39}` |
| 50 | 5.9 (5.0 - 7.9) | 7238.4 (4947.8 - 9209.0) | 14444.1 (12954.3 - 15421.5) | 15901.2 (13870.1 - 16327.5) | `{"200": 622, "201": 35, "503": 4}` |
| 75 | 8.4 (8.1 - 8.7) | 6128.0 (6120.4 - 6475.9) | 15902.5 (15683.5 - 16375.3) | 18028.1 (17819.4 - 18394.0) | `{"200": 661, "201": 29, "503": 249}` |
| 100 | 10.2 (10.2 - 10.6) | 2035.8 (2035.4 - 2104.8) | 21208.0 (19919.6 - 21455.8) | 23820.3 (23047.1 - 24279.5) | `{"200": 443, "201": 20, "503": 691}` |
| 150 | 6.6 (6.6 - 6.8) | 6204.0 (5528.0 - 7011.0) | 31371.2 (31095.4 - 32455.2) | 33489.6 (33075.5 - 34223.8) | `{"200": 208, "201": 11, "503": 540}` |
