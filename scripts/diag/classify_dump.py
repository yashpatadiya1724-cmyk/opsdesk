import sys
import re
from typing import Dict, List, Any

# Classification rules based on top-of-stack / frame contents
# 1. pool checkout wait: sqlalchemy pool _do_get or checkout or queue.get
# 2. lock wait: Lock.acquire, threading.py acquire
# 3. sqlite call: sqlite3.Cursor.execute, pysqlite_cursor_execute
# 4. scoring/Python compute: calculate_queue_score_tier2, evaluate_travel_sla, list_tickets
# 5. serialization: json.dumps, starlette.responses.Response.render
# 6. anyio idle worker: anyio._backends._asyncio or worker thread waiting on queue
# 7. other/unclassified

def classify_thread(lines: List[str]) -> str:
    text = "\n".join(lines)
    if "sqlalchemy" in text and ("_do_get" in text or "checkout" in text or "QueuePool" in text):
        return "pool checkout wait"
    if "threading.py" in text and "acquire" in text:
        return "lock wait"
    if "sqlite3" in text or "pysqlite" in text:
        return "sqlite call"
    if "calculate_queue_score" in text or "evaluate_travel_sla" in text:
        return "scoring/Python compute"
    if "json" in text and ("dumps" in text or "render" in text):
        return "serialization"
    if "anyio" in text and ("worker" in text or "wait" in text or "get" in text):
        return "anyio idle worker"
    return "other/unclassified"

def parse_and_classify_dump(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split by thread blocks: "Thread 0x..."
    thread_blocks = re.split(r"(?=Thread 0x[0-9a-fA-F]+)", content)
    counts = {
        "pool checkout wait": 0,
        "lock wait": 0,
        "sqlite call": 0,
        "scoring/Python compute": 0,
        "serialization": 0,
        "anyio idle worker": 0,
        "other/unclassified": 0
    }
    parsed_threads = []
    for block in thread_blocks:
        block = block.strip()
        if not block.startswith("Thread"):
            continue
        lines = block.splitlines()
        category = classify_thread(lines)
        counts[category] = counts.get(category, 0) + 1
        parsed_threads.append((lines[0], category))

    return {"counts": counts, "threads": parsed_threads}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: classify_dump.py <dump_file>")
        sys.exit(1)
    res = parse_and_classify_dump(sys.argv[1])
    print("=== DUMP THREAD CLASSIFICATION COUNTS ===")
    for cat, count in res["counts"].items():
        print(f"  {cat:<25}: {count}")
    print("\nTotal threads analyzed:", len(res["threads"]))
