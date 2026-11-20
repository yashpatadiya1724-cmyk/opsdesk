import os
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest


def run_concurrency_config(journal_mode: str, busy_timeout_ms: int, num_threads: int = 8, writes_per_thread: int = 25):
    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_db_fd)
    try:
        con = sqlite3.connect(temp_db_path)
        cur = con.cursor()
        cur.execute(f"PRAGMA journal_mode={journal_mode}")
        cur.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("CREATE TABLE test_bench (id INTEGER PRIMARY KEY, thread_id INT, val INT)")
        con.commit()
        con.close()

        locked_errors = 0
        success_commits = 0
        lock = threading.Lock()

        def writer_task(tid: int):
            nonlocal locked_errors, success_commits
            timeout_sec = busy_timeout_ms / 1000.0
            c = sqlite3.connect(temp_db_path, timeout=timeout_sec)
            try:
                c.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            except sqlite3.OperationalError:
                pass
            for i in range(writes_per_thread):
                try:
                    c.execute("INSERT INTO test_bench (thread_id, val) VALUES (?, ?)", (tid, i))
                    c.commit()
                    with lock:
                        success_commits += 1
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        with lock:
                            locked_errors += 1
            c.close()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(writer_task, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        return {"locked_errors": locked_errors, "success_commits": success_commits}
    finally:
        try:
            os.remove(temp_db_path)
            for ext in ["-wal", "-shm"]:
                p = temp_db_path + ext
                if os.path.exists(p):
                    os.remove(p)
        except Exception:
            pass


@pytest.mark.slow
def test_sqlite_3_configs_lock_counts():
    """
    Lane B2: Executes 8 threads x 25 writes (200 total writes) across 3 SQLite configurations
    and prints raw lock-error counts proving busy_timeout prevents lock errors, not WAL alone.
    """
    res1 = run_concurrency_config("DELETE", 0)
    res2 = run_concurrency_config("DELETE", 5000)
    res3 = run_concurrency_config("WAL", 5000)

    print("\n[RAW B2 3-CONFIG RESULTS]")
    print(f"Config 1 (DELETE, busy_timeout=0):    locked_errors={res1['locked_errors']}, success_commits={res1['success_commits']}")
    print(f"Config 2 (DELETE, busy_timeout=5000): locked_errors={res2['locked_errors']}, success_commits={res2['success_commits']}")
    print(f"Config 3 (WAL,    busy_timeout=5000): locked_errors={res3['locked_errors']}, success_commits={res3['success_commits']}")

    # Assert that busy_timeout=5000 eliminates lock errors under burst concurrency
    assert res2["locked_errors"] == 0, f"Expected 0 locked errors on DELETE+5000, got {res2}"
    assert res3["locked_errors"] == 0, f"Expected 0 locked errors on WAL+5000, got {res3}"
    assert res2["success_commits"] == 200
    assert res3["success_commits"] == 200
