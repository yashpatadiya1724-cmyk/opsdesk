import cProfile
import pstats
import io
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

from backend.app.database import ensure_schema_migrations
from backend.app.main import app

def profile_triage():
    # Setup temp DB copy of dev database
    temp_dir = tempfile.mkdtemp()
    temp_db_path = f"{temp_dir}/temp_profile.db"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dev_db = os.path.join(repo_root, "opsdesk.db")
    shutil.copyfile(dev_db, temp_db_path)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import get_db, ensure_schema_migrations
    from backend.app.main import app

    engine = create_engine(f"sqlite:///{temp_db_path}")
    ensure_schema_migrations(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    print("================================================================================")
    print("1. cProfile Top-15 Cumulative Time: Idle Single Request (GET /api/tickets?view=triage)")
    print("================================================================================")
    pr_single = cProfile.Profile()
    pr_single.enable()
    resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
    pr_single.disable()

    s_single = io.StringIO()
    ps_single = pstats.Stats(pr_single, stream=s_single).sort_stats('cumtime')
    ps_single.print_stats(15)
    print(s_single.getvalue())

    print("================================================================================")
    print("2. cProfile Top-15 Cumulative Time: 15-Concurrent Requests (GET /api/tickets?view=triage)")
    print("================================================================================")
    pr_concurrent = cProfile.Profile()
    pr_concurrent.enable()

    def make_req(idx):
        return client.get("/api/tickets?view=triage", headers={"X-User-Id": f"USR-10{idx%4 + 1}"})

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(make_req, i) for i in range(15)]
        for f in futures:
            f.result()

    pr_concurrent.disable()
    s_conc = io.StringIO()
    ps_conc = pstats.Stats(pr_concurrent, stream=s_conc).sort_stats('cumtime')
    ps_conc.print_stats(15)
    print(s_conc.getvalue())

    print("================================================================================")
    print("3. Triage N=5 Latency Runs (Single Request on 5000 rows temp DB)")
    print("================================================================================")
    runs = []
    for r in range(5):
        t0 = time.perf_counter()
        resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
        lat_ms = (time.perf_counter() - t0) * 1000.0
        runs.append(lat_ms)
        print(f"Run {r+1}: {lat_ms:.2f} ms (Status: {resp.status_code}, Candidates Scored: {len(resp.json()['tickets'])})")

    import statistics
    runs_sorted = sorted(runs)
    median_lat = statistics.median(runs)
    print(f"\n[N=5 TRIAGE BENCHMARK] Median: {median_lat:.2f} ms | Min: {runs_sorted[0]:.2f} ms | Max: {runs_sorted[-1]:.2f} ms")

if __name__ == "__main__":
    profile_triage()
