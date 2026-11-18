import os
import sys
import time
import threading
import argparse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import uvicorn
from backend.app.main import app
from backend.app.database import engine

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8008)
    args = parser.parse_args()

    pool_samples_file = os.getenv("POOL_SAMPLES_FILE")
    start_time = time.time()

    def pool_sampler():
        if not pool_samples_file:
            return
        while True:
            now = time.time()
            sec = int(now - start_time) + 1
            try:
                co = engine.pool.checkedout()
            except Exception:
                co = 0
            try:
                with open(pool_samples_file, "a", encoding="utf-8") as f:
                    f.write(f"{sec},{co}\n")
            except Exception:
                pass
            time.sleep(1.0)

    t = threading.Thread(target=pool_sampler, daemon=True)
    t.start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
