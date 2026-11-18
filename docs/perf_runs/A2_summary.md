# A2: Concurrency Collapse Faulthandler Dump Summary

This document summarizes the thread stack classifications captured via `faulthandler.dump_traceback_later` across 10 repeated dump intervals during sustained 100 concurrent client load ($T=0$).

The full raw stack dumps (26,000+ lines) are archived in [`docs/perf_runs/archive/A2_thread_dumps.zip`](archive/A2_thread_dumps.zip) to avoid repository bloat.

---

## 1. Classification Results

### Variant (a) [Normal Seed: ~456 unassigned tickets]
Total classified thread states: 601
- **Pool checkout wait (`_do_get` in `sqlalchemy/pool/base.py`)**: **360** (59.9%)
- **AnyIO worker threads idle (`wait` on queue)**: **213** (35.4%)
- **Lock wait (`threading.Lock.acquire`)**: **0** (0.0%)
- **SQLite internal execution**: **0** (0.0%)
- **Queue scoring / Python compute**: **0** (0.0%)
- **Response serialization**: **0** (0.0%)
- **Other / unclassified (loopback socket / selector)**: **28** (4.7%)

### Variant (b) [Triage Heavy: 5,000 unassigned tickets]
Total classified thread states: 661
- **Pool checkout wait (`_do_get` in `sqlalchemy/pool/base.py`)**: **378** (57.2%)
- **AnyIO worker threads idle (`wait` on queue)**: **211** (31.9%)
- **Lock wait (`threading.Lock.acquire`)**: **0** (0.0%)
- **SQLite internal execution**: **0** (0.0%)
- **Queue scoring / Python compute**: **0** (0.0%)
- **Response serialization**: **0** (0.0%)
- **Other / unclassified (loopback socket / selector)**: **72** (10.9%)

---

## 2. Key Diagnostic Finding
In both variants, over **57% to 60%** of all active worker threads are blocked inside SQLAlchemy `QueuePool._do_get()` attempting to acquire a database connection after the connection pool (configured with `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=20`, total 30 connections) was exhausted. Thread contention is centered entirely on QueuePool checkout, not on SQLite file locks or CPU compute.
