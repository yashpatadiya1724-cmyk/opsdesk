import subprocess
import sys
import os

def test_seed_production_refusal():
    """
    Verifies that running seed_data.py --reset when APP_ENV=production
    strictly refuses execution with return code 1.
    """
    env = os.environ.copy()
    env["APP_ENV"] = "production"

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "seed", "seed_data.py"))

    proc = subprocess.run(
        [sys.executable, script_path, "--reset", "--yes"],
        env=env,
        capture_output=True,
        text=True
    )

    assert proc.returncode == 1
    assert "Safety Refusal: Resetting database is strictly prohibited when APP_ENV=production." in proc.stdout or "Safety Refusal" in proc.stderr
