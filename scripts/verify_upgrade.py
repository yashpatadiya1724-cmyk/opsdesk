"""
Unattended verification script for database upgrade from legacy merge-base 7d39b66.
Writes full raw transcript to docs/verification/upgrade_transcript.txt.
"""
import os
import sys
import shutil
import tempfile
import subprocess
import secrets
import json
from datetime import datetime, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
TRANSCRIPT_PATH = os.path.join(REPO_ROOT, "docs", "verification", "upgrade_transcript.txt")
MERGE_BASE_COMMIT = "7d39b66"


class TranscriptWriter:
    def __init__(self, filepath: str):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.file = open(filepath, "w", encoding="utf-8")

    def print(self, *args, **kwargs):
        line = " ".join(str(a) for a in args)
        print(line, **kwargs)
        self.file.write(line + "\n")
        self.file.flush()

    def close(self):
        self.file.close()


def run_command(cmd, cwd=REPO_ROOT, env=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed (exit {res.returncode}): {' '.join(cmd)}\nStdout: {res.stdout}\nStderr: {res.stderr}")
    return res


def main():
    tw = TranscriptWriter(TRANSCRIPT_PATH)
    tw.print(f"=== UPGRADE VERIFICATION SCRIPT START ===")
    tw.print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    tw.print(f"Merge-base commit: {MERGE_BASE_COMMIT}")

    temp_dir = tempfile.mkdtemp(prefix="opsdesk_upgrade_verify_")
    tw.print(f"Temporary directory: {temp_dir}")
    legacy_db_file = os.path.join(temp_dir, "legacy_test.db")
    legacy_db_url = "sqlite:///" + legacy_db_file.replace("\\", "/")
    worktree_path = os.path.join(temp_dir, "wt_legacy")
    python_exe = sys.executable

    try:
        # 1. Create legacy DB from merge-base 7d39b66 via git worktree
        tw.print("\n--- STEP 1: Creating legacy database from merge-base 7d39b66 ---")
        run_command(["git", "worktree", "add", worktree_path, "--detach", MERGE_BASE_COMMIT])
        tw.print(f"Added detached git worktree at {worktree_path} (commit {MERGE_BASE_COMMIT})")

        seed_env = dict(os.environ, DATABASE_URL=legacy_db_url)
        seed_res = run_command(
            [python_exe, "-m", "backend.seed.seed_data", "--reset", "--yes"],
            cwd=worktree_path,
            env=seed_env
        )
        tw.print(f"Seeded legacy database via worktree (exit {seed_res.returncode}):")
        for line in seed_res.stdout.strip().splitlines()[-5:]:
            tw.print(f"  {line}")

        # Clean up worktree immediately
        run_command(["git", "worktree", "remove", "--force", worktree_path])
        tw.print("Removed temporary git worktree")

        # 2. Run scripts/upgrade_legacy_db.py
        tw.print("\n--- STEP 2: Running scripts/upgrade_legacy_db.py ---")
        upgrade_res = run_command(
            [python_exe, "scripts/upgrade_legacy_db.py", "--db-url", legacy_db_url],
            cwd=REPO_ROOT
        )
        tw.print(f"Upgrade script output (exit {upgrade_res.returncode}):")
        for line in upgrade_res.stdout.strip().splitlines():
            tw.print(f"  {line}")

        # 3. Print PRAGMA table_info for tickets, users, agencies
        tw.print("\n--- STEP 3: PRAGMA table_info for tickets, users, agencies ---")
        import sqlite3
        conn = sqlite3.connect(legacy_db_file)
        cur = conn.cursor()

        tw.print("PRAGMA table_info(tickets):")
        for col in cur.execute("PRAGMA table_info(tickets)").fetchall():
            tw.print(f"  {col}")

        tw.print("PRAGMA table_info(users):")
        for col in cur.execute("PRAGMA table_info(users)").fetchall():
            tw.print(f"  {col}")

        tw.print("PRAGMA table_info(agencies):")
        for col in cur.execute("PRAGMA table_info(agencies)").fetchall():
            tw.print(f"  {col}")
        conn.close()

        # 4. Run app via TestClient against upgraded DB
        tw.print("\n--- STEP 4: TestClient GET /api/tickets?view=triage&limit=3 and GET /api/tickets/{id} ---")
        os.environ["DATABASE_URL"] = legacy_db_url
        os.environ["AUTH_MODE"] = "demo"

        # Import app modules after setting env
        from backend.app import database as db_mod
        from sqlalchemy.orm import sessionmaker
        db_mod.engine = db_mod.create_db_engine(legacy_db_url)
        db_mod.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_mod.engine)
        from backend.app import main as main_mod
        from fastapi.testclient import TestClient

        client = TestClient(main_mod.app)

        triage_resp = client.get("/api/tickets?view=triage&limit=3", headers={"X-User-Id": "USR-101"})
        tw.print(f"GET /api/tickets?view=triage&limit=3 status: {triage_resp.status_code}")
        triage_json = triage_resp.json()
        tw.print(f"GET /api/tickets?view=triage&limit=3 response:")
        tw.print(json.dumps(triage_json, indent=2))

        first_id = triage_json["tickets"][0]["id"]
        tw.print(f"\nFirst ticket ID for detail lookup: {first_id}")

        detail_resp = client.get(f"/api/tickets/{first_id}", headers={"X-User-Id": "USR-101"})
        tw.print(f"GET /api/tickets/{first_id} status: {detail_resp.status_code}")
        detail_json = detail_resp.json()
        tw.print(f"GET /api/tickets/{first_id} response:")
        tw.print(json.dumps(detail_json, indent=2))

        # 5. Run manage set-password
        tw.print("\n--- STEP 5: Running python -m backend.app.manage set-password ---")
        new_password = "Verified_Password_2026_Secure!"
        pwd_res = run_command(
            [
                python_exe, "-m", "backend.app.manage", "set-password",
                "--email", "aisha.ops@tbo.test",
                "--password", new_password
            ],
            cwd=REPO_ROOT,
            env=dict(os.environ, DATABASE_URL=legacy_db_url)
        )
        tw.print(f"set-password command output (exit {pwd_res.returncode}):")
        for line in pwd_res.stdout.strip().splitlines():
            tw.print(f"  {line}")

        # 6. Login with AUTH_MODE=jwt and generated 40-char JWT_SECRET
        tw.print("\n--- STEP 6: Login with AUTH_MODE=jwt and generated 40-char JWT_SECRET ---")
        generated_jwt_secret = secrets.token_urlsafe(30)[:40]
        assert len(generated_jwt_secret) == 40, f"Secret length must be 40, got {len(generated_jwt_secret)}"
        tw.print(f"Generated 40-char JWT_SECRET: {generated_jwt_secret} (len={len(generated_jwt_secret)})")

        os.environ["AUTH_MODE"] = "jwt"
        os.environ["JWT_SECRET"] = generated_jwt_secret
        from backend.app import auth as auth_mod
        auth_mod.AUTH_MODE = "jwt"
        auth_mod.JWT_SECRET = generated_jwt_secret
        main_mod.AUTH_MODE = "jwt"

        login_resp = client.post(
            "/api/auth/login",
            json={"email": "aisha.ops@tbo.test", "password": new_password}
        )
        tw.print(f"POST /api/auth/login status: {login_resp.status_code}")
        login_json = login_resp.json()
        tw.print(f"POST /api/auth/login response:")
        tw.print(json.dumps(login_json, indent=2))

        token = login_json["access_token"]
        tw.print(f"\nReceived JWT access_token: {token[:20]}...{token[-10:]}")

        # 7. Decode returned token and print payload with exp as UTC date and iat
        tw.print("\n--- STEP 7: Decoded JWT Token Payload ---")
        import jwt as pyjwt
        decoded_payload = pyjwt.decode(token, generated_jwt_secret, algorithms=["HS256"])
        exp_timestamp = decoded_payload.get("exp")
        iat_timestamp = decoded_payload.get("iat")
        exp_utc = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc).isoformat() if exp_timestamp else None
        iat_utc = datetime.fromtimestamp(iat_timestamp, tz=timezone.utc).isoformat() if iat_timestamp else None

        tw.print(f"Decoded raw payload: {json.dumps(decoded_payload, indent=2)}")
        tw.print(f"iat (Issued At): {iat_timestamp} ({iat_utc})")
        tw.print(f"exp (Expires At): {exp_timestamp} ({exp_utc})")
        assert exp_timestamp is not None and iat_timestamp is not None
        assert exp_timestamp > iat_timestamp, "exp must be after iat"

        # 8. Call GET /api/tickets with Bearer token
        tw.print("\n--- STEP 8: GET /api/tickets with Bearer token ---")
        bearer_resp = client.get(
            "/api/tickets?limit=3",
            headers={"Authorization": f"Bearer {token}"}
        )
        tw.print(f"GET /api/tickets with Bearer token status: {bearer_resp.status_code}")
        bearer_json = bearer_resp.json()
        tw.print(f"GET /api/tickets with Bearer token response:")
        tw.print(json.dumps(bearer_json, indent=2))

        tw.print("\n=== UPGRADE VERIFICATION SCRIPT COMPLETED SUCCESSFULLY ===")

    finally:
        tw.close()
        # Clean up temp dir
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Transcript written to {TRANSCRIPT_PATH}")


if __name__ == "__main__":
    main()
