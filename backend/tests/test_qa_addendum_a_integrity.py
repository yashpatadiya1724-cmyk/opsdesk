import os
import subprocess
import sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

FORBIDDEN_WORDS = ["Synthetic", "Expected Plan", "Template", "Dry-run"]


def test_no_fake_benchmark_words_in_bench_scale():
    """Asserts that scripts/bench_scale.py does not contain fake benchmark templates or forbidden words."""
    bench_scale_path = os.path.join(REPO_ROOT, "scripts", "bench_scale.py")
    with open(bench_scale_path, "r", encoding="utf-8") as f:
        content = f.read()

    for word in FORBIDDEN_WORDS:
        assert word not in content, f"Forbidden word '{word}' found in scripts/bench_scale.py"


def test_no_fake_benchmark_words_in_scale_transcript():
    """Asserts that docs/verification/scale_transcript.txt does not contain forbidden synthetic words if it exists."""
    transcript_path = os.path.join(REPO_ROOT, "docs", "verification", "scale_transcript.txt")
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read()
        for word in FORBIDDEN_WORDS:
            assert word not in content, f"Forbidden word '{word}' found in scale_transcript.txt"


def test_bench_scale_exits_nonzero_without_postgres(tmp_path):
    """Asserts that scripts/bench_scale.py exits non-zero and refuses to generate fake transcripts when PG is missing."""
    out_file = str(tmp_path / "scale_transcript.txt")
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///./test_fake.db"
    res = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "bench_scale.py"), "--output", out_file],
        capture_output=True,
        text=True,
        env=env
    )
    assert res.returncode != 0, f"bench_scale.py must exit non-zero when PostgreSQL is missing! Output: {res.stdout}"
    assert not os.path.exists(out_file), "bench_scale.py must not generate a transcript file when PostgreSQL is missing"


def test_frontend_package_lock_in_sync():
    """ADDENDUM A4: Asserts that frontend/package.json and package-lock.json are strictly in sync."""
    frontend_dir = os.path.join(REPO_ROOT, "frontend")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    res = subprocess.run(
        [npm_cmd, "ci", "--dry-run"],
        cwd=frontend_dir,
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f"npm ci --dry-run failed! package.json and package-lock.json are out of sync: {res.stderr}\n{res.stdout}"
