import os
import sys
import time
import threading
import argparse
import faulthandler
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.app.main import app
from backend.app.database import engine

def start_pool_monitor(pool_log_path: str):
    def monitor_loop():
        with open(pool_log_path, "a", encoding="utf-8") as f:
            while True:
                ts = datetime.utcnow().isoformat()
                active_threads = threading.active_count()
                try:
                    p_status = engine.pool.status()
                except Exception as e:
                    p_status = f"error: {e}"
                line = f"[{ts}] threads={active_threads} pool={p_status}\n"
                f.write(line)
                f.flush()
                time.sleep(5)

    t = threading.Thread(target=monitor_loop, daemon=True, name="pool_monitor_thread")
    t.start()

def main():
    parser = argparse.ArgumentParser(description="OpsDesk Diagnostic Debug Server")
    parser.add_argument("--port", type=int, default=8135, help="Port to bind")
    parser.add_argument("--dump-file", default=None, help="Path for faulthandler thread dumps")
    parser.add_argument("--pool-log", default=None, help="Path for pool status log")
    args = parser.parse_args()

    port = args.port
    dump_file_path = args.dump_file or os.path.join(REPO_ROOT, "docs", "perf_runs", "debug_dump.txt")
    pool_log_path = args.pool_log or os.path.join(REPO_ROOT, "docs", "perf_runs", "pool_status.txt")

    if os.environ.get("OPSDESK_DEBUG_DUMP") == "1":
        dump_f = open(dump_file_path, "w", encoding="utf-8")
        dump_f.write(f"=== Faulthandler Dump Started at {datetime.utcnow().isoformat()} ===\n")
        dump_f.flush()
        faulthandler.dump_traceback_later(10, repeat=True, file=dump_f)

    start_pool_monitor(pool_log_path)

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, log_level="warning")

if __name__ == "__main__":
    main()
