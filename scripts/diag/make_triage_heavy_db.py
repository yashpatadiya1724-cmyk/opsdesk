import os
import sys
import shutil
import sqlite3

def make_triage_heavy_db(src_db: str, dst_db: str) -> int:
    """
    Creates a variant (b) 'triage-heavy' database copy where all tickets
    are unassigned and active for worst-case triage scoring diagnosis.
    Dev DB is never touched.
    """
    shutil.copyfile(src_db, dst_db)
    conn = sqlite3.connect(dst_db)
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET assigned_to = NULL, status = 'Open'")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE assigned_to IS NULL")
    unassigned_count = cur.fetchone()[0]
    conn.close()
    return unassigned_count

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: make_triage_heavy_db.py <src_db> <dst_db>")
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2]
    cnt = make_triage_heavy_db(src, dst)
    print(f"Created triage-heavy DB at {dst} with {cnt} unassigned tickets.")
