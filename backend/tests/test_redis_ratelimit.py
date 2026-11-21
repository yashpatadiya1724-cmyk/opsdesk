import os
import sys
import time
import json
import socket
import logging
import subprocess
import pytest
import httpx
from fastapi.testclient import TestClient

from backend.app.rate_limiter import RedisRateLimiter, InMemoryRateLimiter, get_rate_limiter
from backend.app import main as main_module


def is_redis_available() -> bool:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return False
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        return bool(client.ping())
    except Exception:
        return False


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ============================================================================
# 1. UNIT TESTS: CIRCUIT BREAKER & FALLBACK (RUN WITHOUT REAL REDIS)
# ============================================================================

def test_circuit_breaker_switches_to_fallback_after_3_failures(monkeypatch, caplog):
    """
    2.3 Circuit breaker: after N failures (3 consecutive failures),
    switch to fallback for 30s cooldown before retrying Redis; never fall back permanently.
    """
    caplog.clear()

    class FailingRedisClient:
        def __init__(self):
            self.calls = 0

        def eval(self, *args, **kwargs):
            self.calls += 1
            raise ConnectionError("Redis server connection refused")

        def ping(self):
            raise ConnectionError("Redis ping refused")

    mock_client = FailingRedisClient()
    limiter = RedisRateLimiter(redis_client=mock_client, cooldown_seconds=30.0)

    # First 3 failures should trigger fallback
    limiter.is_rate_limited("cb_test", 5, 60.0)
    assert limiter.consecutive_failures == 1
    assert limiter.circuit_open_until == 0.0

    limiter.is_rate_limited("cb_test", 5, 60.0)
    assert limiter.consecutive_failures == 2
    assert limiter.circuit_open_until == 0.0

    limiter.is_rate_limited("cb_test", 5, 60.0)
    assert limiter.consecutive_failures == 3
    assert limiter.circuit_open_until > time.time()  # Circuit open!
    assert limiter.status == "fallback"

    # Next call uses fallback without calling mock_client
    initial_calls = mock_client.calls
    res = limiter.is_rate_limited("cb_test", 5, 60.0)
    assert mock_client.calls == initial_calls  # Skipped because circuit is open
    assert res is False

    # Dynamic recovery after cooldown: patch circuit_open_until into the past
    limiter.circuit_open_until = time.time() - 1.0

    # Now make mock_client succeed
    class WorkingRedisClient:
        def eval(self, *args, **kwargs):
            return 0

        def ping(self):
            return True

    limiter.redis = WorkingRedisClient()
    assert limiter.is_rate_limited("cb_test", 5, 60.0) is False
    assert limiter.consecutive_failures == 0
    assert limiter.status == "redis"


def test_warning_logged_at_most_once_per_minute_in_fallback(caplog):
    """
    2.3 Log a WARNING at most once per minute while in fallback.
    """
    class AlwaysFailingRedisClient:
        def eval(self, *args, **kwargs):
            raise ConnectionError("Redis unreachable")

        def ping(self):
            raise ConnectionError("Redis ping failed")

    rl_logger = logging.getLogger("opsdesk.ratelimit")
    rl_logger.disabled = False
    rl_logger.setLevel(logging.WARNING)
    with caplog.at_level(logging.WARNING, logger="opsdesk.ratelimit"):
        limiter = RedisRateLimiter(redis_client=AlwaysFailingRedisClient(), cooldown_seconds=60.0)

        # Trigger circuit breaker with 5 calls
        for _ in range(5):
            limiter.is_rate_limited("throttle_log_test", 5, 60.0)

        # Check how many WARNINGs were logged with event=rate_limiter_fallback
        fallback_logs = [
            r for r in caplog.records
            if "rate_limiter_fallback" in r.message
        ]
        # Should be at most 1 warning within this 1-minute window
        assert len(fallback_logs) == 1

        # Calling again immediately should NOT produce another warning
        limiter.is_rate_limited("throttle_log_test", 5, 60.0)
        fallback_logs_after = [
            r for r in caplog.records
            if "rate_limiter_fallback" in r.message
        ]
        assert len(fallback_logs_after) == 1


def test_ready_endpoint_exposes_rate_limiter_status(client: TestClient, monkeypatch):
    """
    2.3 In /ready endpoint: expose 'rate_limiter': 'redis|fallback'.
    """
    # 1. With inmemory / fallback limiter
    monkeypatch.setattr(main_module, "_rate_limiter", InMemoryRateLimiter())
    resp1 = client.get("/ready")
    assert resp1.status_code == 200
    assert resp1.json().get("rate_limiter") == "fallback"

    # 2. With healthy Redis limiter
    class FakeHealthyRedis:
        def ping(self):
            return True

    healthy_limiter = RedisRateLimiter(redis_client=FakeHealthyRedis())
    monkeypatch.setattr(main_module, "_rate_limiter", healthy_limiter)
    resp2 = client.get("/ready")
    assert resp2.status_code == 200
    assert resp2.json().get("rate_limiter") == "redis"

    # 3. With failing Redis limiter (circuit open)
    class FakeBrokenRedis:
        def ping(self):
            raise ConnectionError("down")

    broken_limiter = RedisRateLimiter(redis_client=FakeBrokenRedis())
    monkeypatch.setattr(main_module, "_rate_limiter", broken_limiter)
    resp3 = client.get("/ready")
    assert resp3.status_code == 200
    assert resp3.json().get("rate_limiter") == "fallback"


def test_rate_limit_fail_mode(monkeypatch):
    """
    2.3 Env RATE_LIMIT_FAIL_MODE=open|closed (default open; for login failure buckets default closed).
    """
    class CrashingRedisClient:
        def eval(self, *args, **kwargs):
            raise ConnectionError("Broken connection")

    limiter = RedisRateLimiter(redis_client=CrashingRedisClient())
    limiter.fallback = None  # Simulate fallback unavailable

    # Normal key with fail-open (default) -> returns False (allowed)
    monkeypatch.setenv("RATE_LIMIT_FAIL_MODE", "open")
    assert limiter.is_rate_limited("normal_key", 5, 60.0) is False

    # Normal key with fail-closed -> returns True (blocked)
    monkeypatch.setenv("RATE_LIMIT_FAIL_MODE", "closed")
    assert limiter.is_rate_limited("normal_key", 5, 60.0) is True

    # Login failure bucket defaults to closed even if RATE_LIMIT_FAIL_MODE=open
    monkeypatch.setenv("RATE_LIMIT_FAIL_MODE", "open")
    assert limiter.is_rate_limited("login_fail:email:admin@corp.com", 5, 900.0) is True


# ============================================================================
# 2. INTEGRATION TESTS: REQUIRES REAL REDIS VIA REDIS_URL
# ============================================================================

@pytest.mark.skipif(not is_redis_available(), reason="Redis server not configured via REDIS_URL or not reachable")
def test_redis_limit_shared_across_4_workers():
    """
    2.4 Limit shared across 4 uvicorn workers (limit 60 allows exactly 60).
    Starts a real uvicorn server with --workers 4 against REDIS_URL.
    Sends 80 requests from a single client IP.
    Verifies exactly 60x 200 OK and 20x 429 Too Many Requests.
    """
    port = get_free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["RATE_LIMIT_BACKEND"] = "redis"
    env["RATE_LIMIT_PER_MINUTE"] = "60"
    env["RATE_LIMIT_FAIL_MODE"] = "open"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "4",
            "--log-level",
            "warning"
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        base_url = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(80):
            try:
                r = httpx.get(f"{base_url}/ready", timeout=0.5)
                if r.status_code == 200 and r.json().get("rate_limiter") == "redis":
                    ready = True
                    break
            except Exception:
                time.sleep(0.1)

        assert ready, "4-worker uvicorn server failed to report ready with redis rate limiter"

        status_counts = {}
        with httpx.Client(base_url=base_url) as client:
            for _ in range(80):
                resp = client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
                status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1

        assert status_counts.get(200, 0) == 60, f"Expected 60 allowed requests, got {status_counts}"
        assert status_counts.get(429, 0) == 20, f"Expected 20 rate limited requests, got {status_counts}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not is_redis_available(), reason="Redis server not configured via REDIS_URL or not reachable")
def test_redis_reconnect_after_temporary_failure():
    """
    2.4 Redis hanging / killed: fallback works and Redis is used again after restart.
    """
    real_redis_url = os.environ.get("REDIS_URL")
    limiter = RedisRateLimiter(redis_url=real_redis_url, cooldown_seconds=0.2)
    assert limiter.status == "redis"

    # Simulate connection dropping by temporarily setting a non-routable port
    limiter.redis_url = "redis://127.0.0.1:54321/0"
    limiter.redis = None

    # 3 failures will trip circuit breaker into fallback
    for _ in range(3):
        limiter.is_rate_limited("reconnect_test", 10, 60.0)

    assert limiter.status == "fallback"

    # Fallback in-memory works while Redis is down
    assert limiter.is_rate_limited("reconnect_test", 10, 60.0) is False

    # Restore correct redis URL and wait for 0.2s cooldown
    limiter.redis_url = real_redis_url
    time.sleep(0.3)

    # Dynamic recovery: next call connects to Redis and resets status to redis
    assert limiter.is_rate_limited("reconnect_test", 10, 60.0) is False
    assert limiter.status == "redis"
