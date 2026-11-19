import io
import csv
import uuid
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket, User
from backend.app.rate_limiter import (
    RateLimiter,
    InMemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
    get_client_ip
)
from backend.app import main as main_module


class MockRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def zremrangebyscore(self, key, min_val, max_val):
        self.ops.append(("zrem", key, min_val, max_val))
        return self

    def zcard(self, key):
        self.ops.append(("zcard", key))
        return self

    def zadd(self, key, mapping):
        self.ops.append(("zadd", key, mapping))
        return self

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))
        return self

    def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "zrem":
                self.client.zremrangebyscore(op[1], op[2], op[3])
                results.append(1)
            elif op[0] == "zcard":
                results.append(self.client.zcard(op[1]))
            elif op[0] == "zadd":
                self.client.zadd(op[1], op[2])
                results.append(1)
            elif op[0] == "expire":
                self.client.expire(op[1], op[2])
                results.append(True)
        self.ops.clear()
        return results


class MockRedisClient:
    def __init__(self, supports_pipeline=True):
        self.zsets = {}
        self.expirations = {}
        self.supports_pipeline = supports_pipeline

    def pipeline(self):
        if not self.supports_pipeline:
            raise AttributeError("Pipeline not supported")
        return MockRedisPipeline(self)

    def zremrangebyscore(self, key, min_val, max_val):
        if key in self.zsets:
            self.zsets[key] = {
                member: score for member, score in self.zsets[key].items()
                if not (min_val <= score <= max_val)
            }

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zadd(self, key, mapping):
        if key not in self.zsets:
            self.zsets[key] = {}
        self.zsets[key].update(mapping)

    def expire(self, key, seconds):
        self.expirations[key] = seconds

    def ping(self):
        return True


# ============================================================================
# 1. CURSOR-BASED EXPORT PAGINATION TESTS
# ============================================================================

def test_export_tickets_cursor_pagination(client: TestClient, db_session: Session):
    """
    Verifies cursor-based export pagination:
    1. Export first page with limit=5 -> receive X-Next-Cursor header and NEXT_CURSOR in body.
    2. Export second page with cursor=<X-Next-Cursor> and limit=5.
    3. Verify no duplicate tickets and contiguous records matching database ordering.
    """
    # Fetch page 1
    resp1 = client.get("/api/export/tickets.csv?limit=5", headers={"X-User-Id": "USR-104"})
    assert resp1.status_code == 200
    cursor1 = resp1.headers.get("X-Next-Cursor")
    assert cursor1 is not None, "Expected X-Next-Cursor header on page 1"

    reader1 = csv.reader(io.StringIO(resp1.text))
    rows1 = [r for r in reader1 if r and not r[0].startswith("#")]
    assert len(rows1) == 6, f"Expected 1 header + 5 rows, got {len(rows1)}"
    header1 = rows1[0]
    data1 = rows1[1:]
    page1_ids = [r[0] for r in data1]
    assert len(page1_ids) == 5
    assert page1_ids[-1] == cursor1
    # Verify cursor is strictly in the header, never as a comment row in the CSV body
    assert "# [NEXT_CURSOR:" not in resp1.text

    # Fetch page 2 using cursor1
    resp2 = client.get(f"/api/export/tickets.csv?limit=5&cursor={cursor1}", headers={"X-User-Id": "USR-104"})
    assert resp2.status_code == 200
    cursor2 = resp2.headers.get("X-Next-Cursor")
    assert cursor2 is not None, "Expected X-Next-Cursor header on page 2"

    reader2 = csv.reader(io.StringIO(resp2.text))
    rows2 = [r for r in reader2 if r and not r[0].startswith("#")]
    assert len(rows2) == 6, f"Expected 1 header + 5 rows, got {len(rows2)}"
    data2 = rows2[1:]
    page2_ids = [r[0] for r in data2]
    assert len(page2_ids) == 5
    assert page2_ids[-1] == cursor2
    # Verify cursor is strictly in the header, never as a comment row in the CSV body
    assert "# [NEXT_CURSOR:" not in resp2.text

    # Verification: Disjoint (no duplicates) and contiguous (no gaps)
    assert set(page1_ids).isdisjoint(set(page2_ids)), "Pages 1 and 2 must not contain duplicate tickets"

    # Verify against stable query order in DB: order_by(Ticket.created_at.desc(), Ticket.id.desc())
    expected_top_10 = (
        db_session.query(Ticket.id)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(10)
        .all()
    )
    expected_ids = [t[0] for t in expected_top_10]
    assert (page1_ids + page2_ids) == expected_ids, "Export rows must be contiguous with no gaps"


def test_export_default_limit_without_limit_param_returns_x_next_cursor(client: TestClient, db_session: Session, monkeypatch):
    """
    Verifies that when limit is not given, CSV_EXPORT_DEFAULT_LIMIT is applied:
    - X-Next-Cursor is returned when more rows exist.
    - Following cursor returns remaining rows with no overlap or gap.
    - Body contains only header and data rows, with no line starting with '#'.
    """
    monkeypatch.setenv("CSV_EXPORT_DEFAULT_LIMIT", "5")

    # Fetch page 1 without ?limit
    resp1 = client.get("/api/export/tickets.csv", headers={"X-User-Id": "USR-104"})
    assert resp1.status_code == 200
    cursor1 = resp1.headers.get("X-Next-Cursor")
    assert cursor1 is not None, "Expected X-Next-Cursor header when DB has more rows than default limit"

    # Verify no line in body starts with '#'
    lines1 = [line.strip() for line in resp1.text.splitlines() if line.strip()]
    for line in lines1:
        assert not line.startswith("#"), f"CSV body must not contain comment rows, got: {line}"

    reader1 = csv.reader(io.StringIO(resp1.text))
    rows1 = list(reader1)
    assert len(rows1) == 6, f"Expected 1 header + 5 data rows, got {len(rows1)}"
    data1_ids = [r[0] for r in rows1[1:]]

    # Fetch page 2 using cursor1
    resp2 = client.get(f"/api/export/tickets.csv?cursor={cursor1}", headers={"X-User-Id": "USR-104"})
    assert resp2.status_code == 200

    lines2 = [line.strip() for line in resp2.text.splitlines() if line.strip()]
    for line in lines2:
        assert not line.startswith("#"), f"CSV body must not contain comment rows, got: {line}"

    reader2 = csv.reader(io.StringIO(resp2.text))
    rows2 = list(reader2)
    data2_ids = [r[0] for r in rows2[1:]]

    # No overlap (disjoint)
    assert set(data1_ids).isdisjoint(set(data2_ids)), "Pages 1 and 2 must have no overlap"

    # Contiguous with no gap
    expected_top_10 = (
        db_session.query(Ticket.id)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(10)
        .all()
    )
    expected_ids = [t[0] for t in expected_top_10]
    assert (data1_ids + data2_ids) == expected_ids[:len(data1_ids) + len(data2_ids)]


def test_export_tickets_cursor_not_found_404(client: TestClient):
    """Verifies that an unknown cursor ID returns 404 Not Found."""
    resp = client.get("/api/export/tickets.csv?cursor=NONEXISTENT-TCK", headers={"X-User-Id": "USR-104"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_export_tickets_last_page_has_no_next_cursor(client: TestClient, db_session: Session):
    """When all remaining rows fit within the page limit, no X-Next-Cursor header is set."""
    # Fetch second-to-last ticket to use as cursor so we don't serialize 5000 tickets
    total = db_session.query(Ticket).count()
    second_to_last = (
        db_session.query(Ticket)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .offset(max(0, total - 2))
        .first()
    )
    resp = client.get(
        f"/api/export/tickets.csv?cursor={second_to_last.id}&limit=10",
        headers={"X-User-Id": "USR-104"},
    )
    assert resp.status_code == 200
    assert "X-Next-Cursor" not in resp.headers
    assert "# [NEXT_CURSOR:" not in resp.text


# ============================================================================
# 2. SEMAPHORE RELEASE ON CLIENT DISCONNECT / CANCELLATION TESTS
# ============================================================================

def test_export_semaphore_release_on_generator_exit(db_session: Session):
    """
    Simulates client disconnect / cancellation mid-stream by closing the async
    body generator, and verifies semaphore is fully restored.
    """
    import anyio
    initial_val = main_module._export_semaphore._value
    lead_user = db_session.query(User).filter(User.role == "Lead").first()

    # Call endpoint directly to obtain StreamingResponse
    streaming_resp = main_module.export_tickets_csv(
        status=None, agency_id=None, from_date=None, to_date=None,
        cursor=None, limit=10, current_user=lead_user, db=db_session
    )
    # Semaphore was acquired
    assert main_module._export_semaphore._value == initial_val - 1

    # Simulate client disconnect mid-stream by consuming a chunk and closing
    async def run_disconnect():
        chunk = await streaming_resp.body_iterator.asend(None)
        assert len(chunk) > 0
        await streaming_resp.body_iterator.aclose()

    anyio.run(run_disconnect)

    # Semaphore must be restored
    assert main_module._export_semaphore._value == initial_val


def test_export_semaphore_release_on_background_task_fallback(db_session: Session):
    """
    Verifies that the BackgroundTask passed to StreamingResponse safely releases
    the semaphore upon client disconnect or abrupt exit, and is idempotent.
    """
    import anyio
    initial_val = main_module._export_semaphore._value
    lead_user = db_session.query(User).filter(User.role == "Lead").first()

    streaming_resp = main_module.export_tickets_csv(
        status=None, agency_id=None, from_date=None, to_date=None,
        cursor=None, limit=10, current_user=lead_user, db=db_session
    )
    assert main_module._export_semaphore._value == initial_val - 1

    async def run_bg():
        if streaming_resp.background:
            await streaming_resp.background()

    anyio.run(run_bg)
    assert main_module._export_semaphore._value == initial_val

    # Verify calling it again does not double-release
    anyio.run(run_bg)
    assert main_module._export_semaphore._value == initial_val


# ============================================================================
# 3. RATE LIMITER INTERFACE & BACKENDS TESTS
# ============================================================================

def test_in_memory_rate_limiter_allows_up_to_limit_and_blocks():
    """Verifies InMemoryRateLimiter allows up to max_requests and blocks limit + 1."""
    limiter = InMemoryRateLimiter(max_keys=100)
    test_key = f"test-key-{uuid.uuid4()}"
    max_reqs = 5
    window_sec = 60.0

    # 1 to 5: must return False (not rate limited)
    for i in range(max_reqs):
        result = limiter.is_rate_limited(test_key, max_reqs, window_sec)
        assert result is False, f"Request {i + 1} should be allowed"

    # 6th request: must return True (rate limited!)
    assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is True

    # 7th request: still blocked
    assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is True


def test_redis_rate_limiter_with_mocked_redis_pipeline():
    """Verifies RedisRateLimiter with a pipeline-capable mock redis client."""
    mock_redis = MockRedisClient(supports_pipeline=True)
    limiter = RedisRateLimiter(redis_client=mock_redis)
    test_key = "user:42"
    max_reqs = 3
    window_sec = 10.0

    # 1..3: allowed
    for i in range(max_reqs):
        assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is False
    assert mock_redis.zcard(f"ratelimit:{test_key}") == 3

    # 4th request: blocked
    assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is True
    assert mock_redis.zcard(f"ratelimit:{test_key}") == 3


def test_redis_rate_limiter_with_mocked_redis_direct():
    """Verifies RedisRateLimiter with direct calls (no pipeline support)."""
    mock_redis = MockRedisClient(supports_pipeline=False)
    limiter = RedisRateLimiter(redis_client=mock_redis)
    test_key = "user:99"
    max_reqs = 3
    window_sec = 10.0

    # 1..3: allowed
    for i in range(max_reqs):
        assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is False

    # 4th request: blocked
    assert limiter.is_rate_limited(test_key, max_reqs, window_sec) is True


def test_redis_rate_limiter_graceful_fallback_on_connection_error(monkeypatch):
    """
    Verifies that when Redis connection or operations fail, RedisRateLimiter
    logs a warning and falls back gracefully to InMemoryRateLimiter without raising.
    """
    class BrokenRedisClient:
        def zremrangebyscore(self, *args, **kwargs):
            raise ConnectionError("Redis server unreachable")

    broken_client = BrokenRedisClient()
    limiter = RedisRateLimiter(redis_client=broken_client)

    # Should fall back gracefully to InMemoryRateLimiter
    assert limiter.is_rate_limited("fallback-test", 2, 60.0) is False
    assert limiter.is_rate_limited("fallback-test", 2, 60.0) is False
    assert limiter.is_rate_limited("fallback-test", 2, 60.0) is True


def test_get_rate_limiter_factory(monkeypatch):
    """Verifies get_rate_limiter() selects the appropriate backend according to env vars."""
    # Default is inmemory
    monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
    limiter = get_rate_limiter()
    assert isinstance(limiter, InMemoryRateLimiter)

    # Redis backend without REDIS_URL falls back to inmemory
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    limiter = get_rate_limiter()
    assert isinstance(limiter, InMemoryRateLimiter)


# ============================================================================
# 4. PROXY IP SPOOFING & CIDR EXTRACTION TESTS
# ============================================================================

class DummyClient:
    def __init__(self, host: str):
        self.host = host


class DummyRequest:
    def __init__(self, host: str, headers: dict = None):
        self.client = DummyClient(host)
        self.headers = headers or {}


def test_get_client_ip_unit():
    """Unit tests for get_client_ip verifying CIDR checks and X-Forwarded-For validation."""
    trusted_cidrs = "127.0.0.1/32, 10.0.0.0/8, 192.168.1.0/24"

    # Untrusted client sends spoofed header: ignored, host returned
    req_untrusted = DummyRequest("198.51.100.5", {"X-Forwarded-For": "203.0.113.1"})
    assert get_client_ip(req_untrusted, trusted_cidrs=trusted_cidrs) == "198.51.100.5"

    # Trusted client sends X-Forwarded-For: extracted
    req_trusted = DummyRequest("10.0.0.5", {"X-Forwarded-For": "203.0.113.1"})
    assert get_client_ip(req_trusted, trusted_cidrs=trusted_cidrs) == "203.0.113.1"

    # Trusted proxy chaining (client, trusted_proxy): first non-proxy IP returned
    req_chained = DummyRequest("10.0.0.5", {"X-Forwarded-For": "203.0.113.1, 10.0.0.2"})
    assert get_client_ip(req_chained, trusted_cidrs=trusted_cidrs) == "203.0.113.1"

    # Trusted client with missing or invalid header: host returned
    req_invalid = DummyRequest("10.0.0.5", {"X-Forwarded-For": "not-a-valid-ip"})
    assert get_client_ip(req_invalid, trusted_cidrs=trusted_cidrs) == "10.0.0.5"

    # Default empty trusted_cidrs: never trust X-Forwarded-For
    assert get_client_ip(req_trusted, trusted_cidrs="") == "10.0.0.5"


def test_proxy_ip_spoofing_middleware_integration(monkeypatch):
    """
    Integration test verifying rate limiting with TRUSTED_PROXY_CIDRS:
    - Untrusted host '198.51.100.5' sending X-Forwarded-For '203.0.113.1':
      Rate limit applies to '198.51.100.5', NOT '203.0.113.1'.
    - Trusted host '10.0.0.5' sending X-Forwarded-For '203.0.113.1':
      Rate limit applies to '203.0.113.1'.
    """
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 2)

    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    # 1. Untrusted client test
    untrusted_client = TestClient(main_module.app, client=("198.51.100.5", 50000))
    resp1 = untrusted_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    resp2 = untrusted_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    assert resp1.status_code != 429
    assert resp2.status_code != 429

    # 3rd request should trigger 429
    resp3 = untrusted_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    assert resp3.status_code == 429

    # Verify rate limit key was recorded for untrusted host IP, NOT the spoofed header IP
    with main_module._rate_limit_lock:
        assert "ip:198.51.100.5" in main_module._rate_limit_records
        assert "ip:203.0.113.1" not in main_module._rate_limit_records

    # 2. Trusted proxy test
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    trusted_proxy_client = TestClient(main_module.app, client=("10.0.0.5", 50000))
    resp_t1 = trusted_proxy_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    resp_t2 = trusted_proxy_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    assert resp_t1.status_code != 429
    assert resp_t2.status_code != 429

    # 3rd request from same forwarded client IP triggers 429
    resp_t3 = trusted_proxy_client.get("/api/tickets?view=triage", headers={"X-Forwarded-For": "203.0.113.1"})
    assert resp_t3.status_code == 429

    # Verify rate limit key was recorded for the validated forwarded IP
    with main_module._rate_limit_lock:
        assert "ip:203.0.113.1" in main_module._rate_limit_records


def test_cors_preflight_exposes_next_cursor_and_request_id(client: TestClient):
    """
    Verifies that CORS middleware explicitly exposes X-Next-Cursor and X-Request-ID headers.
    """
    # 1. Preflight check
    resp_options = client.options(
        "/api/export/tickets.csv",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-User-Id"
        }
    )
    assert resp_options.status_code == 200
    assert resp_options.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # 2. Actual request with Origin check for Access-Control-Expose-Headers
    resp = client.get(
        "/api/export/tickets.csv?limit=1",
        headers={
            "Origin": "http://localhost:3000",
            "X-User-Id": "USR-104"
        }
    )
    assert resp.status_code == 200
    exposed = resp.headers.get("access-control-expose-headers", "")
    exposed_lower = [h.strip().lower() for h in exposed.split(",")]
    assert "x-next-cursor" in exposed_lower
    assert "x-request-id" in exposed_lower


def test_csv_export_safe_parser_and_streaming_chunked(client: TestClient, monkeypatch, caplog):
    """
    Verifies that:
    1. get_csv_export_default_limit safely parses malformed or negative values and falls back to 50000.
    2. Streaming export streams rows without loading all ORM models at once.
    """
    from backend.app.main import get_csv_export_default_limit

    # Safe parser fallbacks
    monkeypatch.setenv("CSV_EXPORT_DEFAULT_LIMIT", "invalid_number")
    assert get_csv_export_default_limit() == 50000

    monkeypatch.setenv("CSV_EXPORT_DEFAULT_LIMIT", "-50")
    assert get_csv_export_default_limit() == 50000

    monkeypatch.setenv("CSV_EXPORT_DEFAULT_LIMIT", "50,000")
    assert get_csv_export_default_limit() == 50000

    # Stream chunks check
    monkeypatch.setenv("CSV_EXPORT_DEFAULT_LIMIT", "10")
    resp = client.get("/api/export/tickets.csv", headers={"X-User-Id": "USR-104"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Next-Cursor") is not None
    lines = [l for l in resp.text.splitlines() if l.strip()]
    assert len(lines) == 11  # 1 header + 10 data rows

