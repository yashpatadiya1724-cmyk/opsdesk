import sys
import re
from typing import Dict, List, Any

# Classification rules based on top-of-stack / frame contents
# 4 standardized categories:
# 1. sqlite do_execute/commit
# 2. lock acquire
# 3. event-loop/response wait
# 4. other

def classify_thread(lines: List[str]) -> str:
    text = "\n".join(lines).lower()
    # 1. sqlite do_execute/commit
    if ("sqlite" in text or "pysqlite" in text) and ("execute" in text or "commit" in text or "rollback" in text or "cursor" in text):
        return "sqlite do_execute/commit"
    if "do_execute" in text or ("commit" in text and "sqlalchemy" in text):
        return "sqlite do_execute/commit"

    # 2. lock acquire (threading lock/condition, threadpool lock, or pool queue lock)
    if ("acquire" in text or "condition" in text or "lock" in text) and ("threading" in text or "_thread" in text or "queue.py" in text or "synchronize" in text):
        return "lock acquire"

    # 3. event-loop/response wait (asyncio, anyio worker idling, starlette streaming/response)
    if any(k in text for k in ["asyncio", "anyio", "starlette", "uvicorn", "h11", "http"]):
        if any(w in text for w in ["run", "wait", "worker", "send", "receive", "poll", "select", "handle"]):
            return "event-loop/response wait"

    # 4. other
    return "other"

def parse_and_classify_dump(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split by thread blocks: "Thread 0x..."
    thread_blocks = re.split(r"(?=Thread 0x[0-9a-fA-F]+)", content)
    counts = {
        "sqlite do_execute/commit": 0,
        "lock acquire": 0,
        "event-loop/response wait": 0,
        "other": 0
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
