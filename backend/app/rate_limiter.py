from abc import ABC, abstractmethod
import os
import sys
import time
import uuid
import json
import logging
import threading
import ipaddress
import concurrent.futures
from typing import Optional, Dict, List, Any
from fastapi import Request

logger = logging.getLogger("opsdesk.ratelimit")

LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local member = ARGV[5]

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local current_count = redis.call('ZCARD', key)

if current_count >= max_requests then
    return 1
else
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(ttl) + 1)
    return 0
end
"""

LUA_CHECK_RATE_LIMITED = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local max_requests = tonumber(ARGV[2])

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local current_count = redis.call('ZCARD', key)

if current_count >= max_requests then
    return 1
else
    return 0
end
"""

LUA_RECORD_EVENT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local member = ARGV[3]

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(ttl) + 1)
return 1
"""


class RateLimiter(ABC):
    """Abstract base class defining the rate limiter interface."""

    @abstractmethod
    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
        fail_mode: Optional[str] = None
    ) -> bool:
        """
        Check if a given key has exceeded the maximum allowed requests within the time window.
        Returns True if rate limit is exceeded, False otherwise.
        """
        pass

    @abstractmethod
    def check_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float
    ) -> bool:
        """Check whether key exceeds rate limit without recording an attempt."""
        pass

    @abstractmethod
    def record_event(
        self,
        key: str,
        window_seconds: float
    ) -> None:
        """Record an attempt or failure for sliding window tracking."""
        pass

    @abstractmethod
    def reset(self, key: str) -> None:
        """Clear the bucket/state for a given key."""
        pass

    @property
    @abstractmethod
    def status(self) -> str:
        """Expose current limiter status ('redis' or 'fallback')."""
        pass


class InMemoryRateLimiter(RateLimiter):
    """
    In-memory sliding-window rate limiter using threading lock,
    timestamp lists, and bounded dict eviction.
    """

    def __init__(self, max_keys: Optional[int] = None):
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}
        self._explicit_max_keys = max_keys

    @property
    def lock(self) -> threading.Lock:
        main_mod = sys.modules.get("backend.app.main")
        if main_mod and hasattr(main_mod, "_rate_limit_lock") and main_mod._rate_limit_lock is not None:
            return main_mod._rate_limit_lock
        return self._lock

    @property
    def records(self) -> Dict[str, List[float]]:
        main_mod = sys.modules.get("backend.app.main")
        if main_mod and hasattr(main_mod, "_rate_limit_records") and main_mod._rate_limit_records is not None:
            return main_mod._rate_limit_records
        return self._records

    def _get_max_keys(self) -> int:
        if self._explicit_max_keys is not None:
            return self._explicit_max_keys
        main_mod = sys.modules.get("backend.app.main")
        if main_mod and hasattr(main_mod, "RATE_LIMIT_MAX_KEYS"):
            try:
                return int(main_mod.RATE_LIMIT_MAX_KEYS)
            except (ValueError, TypeError):
                pass
        try:
            return int(os.environ.get("RATE_LIMIT_MAX_KEYS", "10000"))
        except (ValueError, TypeError):
            return 10000

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
        fail_mode: Optional[str] = None
    ) -> bool:
        now = time.time()
        window_start = now - window_seconds
        max_keys = self._get_max_keys()

        with self.lock:
            records = self.records
            existing = records.get(key, [])
            active = [t for t in existing if t > window_start]
            if len(active) >= max_requests:
                records[key] = active
                return True

            # Bounded dict eviction: remove stale keys if size exceeds max bound
            if len(records) >= max_keys:
                stale_keys = [k for k, v in records.items() if not v or v[-1] <= window_start]
                for k in stale_keys:
                    del records[k]
                if len(records) >= max_keys:
                    # Drop oldest 10% of entries if still at capacity
                    sorted_keys = sorted(
                        records.keys(),
                        key=lambda k: records[k][-1] if records[k] else 0
                    )
                    for k in sorted_keys[: max(1, len(records) // 10)]:
                        del records[k]

            active.append(now)
            records[key] = active
            return False

    def check_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float
    ) -> bool:
        now = time.time()
        window_start = now - window_seconds
        with self.lock:
            existing = self.records.get(key, [])
            active = [t for t in existing if t > window_start]
            return len(active) >= max_requests

    def record_event(
        self,
        key: str,
        window_seconds: float
    ) -> None:
        now = time.time()
        window_start = now - window_seconds
        with self.lock:
            existing = self.records.get(key, [])
            active = [t for t in existing if t > window_start]
            active.append(now)
            self.records[key] = active

    def reset(self, key: str) -> None:
        with self.lock:
            self.records.pop(key, None)

    @property
    def status(self) -> str:
        return "fallback"


class RedisRateLimiter(RateLimiter):
    """
    Sliding-window rate limiter backed by Redis.
    Uses atomic Lua script (with pipeline fallback) and dynamic circuit breaker.
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        redis_url: Optional[str] = None,
        max_failures: int = 3,
        cooldown_seconds: float = 30.0
    ):
        self.redis: Optional[Any] = redis_client
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0
        self.last_fallback_log_time = 0.0
        self.fallback = InMemoryRateLimiter()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="redis_ratelimit"
        )

        if self.redis is None:
            self._try_connect()

    def _resolve_fail_mode(self, key: str, explicit: Optional[str] = None) -> str:
        if explicit:
            return explicit.lower()
        if key.startswith("login_fail:"):
            return "closed"
        return os.environ.get("RATE_LIMIT_FAIL_MODE", "open").lower()

    def _try_connect(self) -> bool:
        try:
            import redis
            client = redis.from_url(
                self.redis_url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5
            )
            client.ping()
            self.redis = client
            self.consecutive_failures = 0
            self.circuit_open_until = 0.0
            return True
        except Exception as exc:
            self.redis = None
            self._handle_failure(f"Redis connection failed: {exc}")
            return False

    def _handle_failure(self, reason: str):
        now = time.time()
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures:
            self.circuit_open_until = now + self.cooldown_seconds
        self._maybe_log_fallback(reason)

    def _handle_success(self):
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0

    def _maybe_log_fallback(self, reason: str = ""):
        now = time.time()
        if now - self.last_fallback_log_time >= 60.0:
            self.last_fallback_log_time = now
            logger.warning(
                json.dumps({
                    "event": "rate_limiter_fallback",
                    "reason": reason or "Redis unavailable, falling back to InMemoryRateLimiter",
                    "consecutive_failures": self.consecutive_failures,
                    "cooldown_remaining": max(0.0, round(self.circuit_open_until - now, 2))
                })
            )

    def _is_circuit_open(self) -> bool:
        now = time.time()
        if now < self.circuit_open_until:
            self._maybe_log_fallback("Circuit breaker open")
            return True
        return False

    def _execute(self, fn, *args, **kwargs):
        future = self._executor.submit(fn, *args, **kwargs)
        return future.result(timeout=0.6)

    @property
    def status(self) -> str:
        if self._is_circuit_open():
            return "fallback"
        if self.redis is None:
            if not self._try_connect():
                return "fallback"
        try:
            self._execute(self.redis.ping)
            return "redis"
        except Exception:
            self._handle_failure("Redis ping failed")
            return "fallback"

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
        fail_mode: Optional[str] = None
    ) -> bool:
        mode = self._resolve_fail_mode(key, fail_mode)

        if self._is_circuit_open():
            if self.fallback is not None:
                return self.fallback.is_rate_limited(key, max_requests, window_seconds, fail_mode)
            return True if mode == "closed" else False

        if self.redis is None:
            if not self._try_connect():
                if self.fallback is not None:
                    return self.fallback.is_rate_limited(key, max_requests, window_seconds, fail_mode)
                return True if mode == "closed" else False

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"
        member = f"{now}:{uuid.uuid4().hex}"

        def _do_redis():
            # Attempt atomic Lua script EVAL
            if hasattr(self.redis, "eval") and callable(self.redis.eval):
                try:
                    res = self.redis.eval(
                        LUA_SLIDING_WINDOW,
                        1,
                        redis_key,
                        str(now),
                        str(window_start),
                        str(max_requests),
                        str(window_seconds),
                        member
                    )
                    return bool(int(res) == 1)
                except Exception:
                    pass

            # Fallback to pipeline
            if hasattr(self.redis, "pipeline"):
                try:
                    pipe = self.redis.pipeline()
                    pipe.zremrangebyscore(redis_key, 0, window_start)
                    pipe.zcard(redis_key)
                    res = pipe.execute()
                    current_count = res[1] if isinstance(res, (list, tuple)) and len(res) > 1 else self.redis.zcard(redis_key)
                except Exception:
                    self.redis.zremrangebyscore(redis_key, 0, window_start)
                    current_count = self.redis.zcard(redis_key)
            else:
                self.redis.zremrangebyscore(redis_key, 0, window_start)
                current_count = self.redis.zcard(redis_key)

            if current_count >= max_requests:
                return True

            if hasattr(self.redis, "pipeline"):
                try:
                    pipe = self.redis.pipeline()
                    pipe.zadd(redis_key, {member: now})
                    pipe.expire(redis_key, int(window_seconds) + 1)
                    pipe.execute()
                except Exception:
                    self.redis.zadd(redis_key, {member: now})
                    self.redis.expire(redis_key, int(window_seconds) + 1)
            else:
                self.redis.zadd(redis_key, {member: now})
                self.redis.expire(redis_key, int(window_seconds) + 1)

            return False

        try:
            result = self._execute(_do_redis)
            self._handle_success()
            return result
        except Exception as exc:
            self._handle_failure(f"Redis operation error: {exc}")
            if self.fallback is not None:
                return self.fallback.is_rate_limited(key, max_requests, window_seconds, fail_mode)
            return True if mode == "closed" else False

    def check_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float
    ) -> bool:
        mode = self._resolve_fail_mode(key)
        if self._is_circuit_open():
            if self.fallback is not None:
                return self.fallback.check_rate_limited(key, max_requests, window_seconds)
            return True if mode == "closed" else False

        if self.redis is None:
            if not self._try_connect():
                if self.fallback is not None:
                    return self.fallback.check_rate_limited(key, max_requests, window_seconds)
                return True if mode == "closed" else False

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        def _do_check():
            if hasattr(self.redis, "eval") and callable(self.redis.eval):
                try:
                    res = self.redis.eval(
                        LUA_CHECK_RATE_LIMITED,
                        1,
                        redis_key,
                        str(window_start),
                        str(max_requests)
                    )
                    return bool(int(res) == 1)
                except Exception:
                    pass

            if hasattr(self.redis, "pipeline"):
                try:
                    pipe = self.redis.pipeline()
                    pipe.zremrangebyscore(redis_key, 0, window_start)
                    pipe.zcard(redis_key)
                    res = pipe.execute()
                    current_count = res[1] if isinstance(res, (list, tuple)) and len(res) > 1 else self.redis.zcard(redis_key)
                except Exception:
                    self.redis.zremrangebyscore(redis_key, 0, window_start)
                    current_count = self.redis.zcard(redis_key)
            else:
                self.redis.zremrangebyscore(redis_key, 0, window_start)
                current_count = self.redis.zcard(redis_key)

            return current_count >= max_requests

        try:
            result = self._execute(_do_check)
            self._handle_success()
            return result
        except Exception as exc:
            self._handle_failure(f"Redis check error: {exc}")
            if self.fallback is not None:
                return self.fallback.check_rate_limited(key, max_requests, window_seconds)
            return True if mode == "closed" else False

    def record_event(
        self,
        key: str,
        window_seconds: float
    ) -> None:
        if self._is_circuit_open():
            if self.fallback is not None:
                self.fallback.record_event(key, window_seconds)
            return

        if self.redis is None:
            if not self._try_connect():
                if self.fallback is not None:
                    self.fallback.record_event(key, window_seconds)
                return

        now = time.time()
        redis_key = f"ratelimit:{key}"
        member = f"{now}:{uuid.uuid4().hex}"

        def _do_record():
            if hasattr(self.redis, "eval") and callable(self.redis.eval):
                try:
                    self.redis.eval(
                        LUA_RECORD_EVENT,
                        1,
                        redis_key,
                        str(now),
                        str(window_seconds),
                        member
                    )
                    return
                except Exception:
                    pass

            if hasattr(self.redis, "pipeline"):
                try:
                    pipe = self.redis.pipeline()
                    pipe.zadd(redis_key, {member: now})
                    pipe.expire(redis_key, int(window_seconds) + 1)
                    pipe.execute()
                except Exception:
                    self.redis.zadd(redis_key, {member: now})
                    self.redis.expire(redis_key, int(window_seconds) + 1)
            else:
                self.redis.zadd(redis_key, {member: now})
                self.redis.expire(redis_key, int(window_seconds) + 1)

        try:
            self._execute(_do_record)
            self._handle_success()
        except Exception as exc:
            self._handle_failure(f"Redis record error: {exc}")
            if self.fallback is not None:
                self.fallback.record_event(key, window_seconds)

    def reset(self, key: str) -> None:
        if self.fallback is not None:
            self.fallback.reset(key)

        if self.redis is not None and not self._is_circuit_open():
            redis_key = f"ratelimit:{key}"
            try:
                def _do_delete():
                    if hasattr(self.redis, "delete"):
                        self.redis.delete(redis_key)

                self._execute(_do_delete)
            except Exception as exc:
                self._handle_failure(f"Redis reset error: {exc}")


def get_rate_limiter() -> RateLimiter:
    """Factory function returning the configured RateLimiter implementation."""
    backend = os.environ.get("RATE_LIMIT_BACKEND", "inmemory").lower()
    redis_url = os.environ.get("REDIS_URL")
    if backend == "redis":
        if redis_url:
            return RedisRateLimiter(redis_url=redis_url)
        else:
            logger.warning("RATE_LIMIT_BACKEND=redis configured but REDIS_URL not set. Falling back to InMemoryRateLimiter.")
            return InMemoryRateLimiter()
    return InMemoryRateLimiter()


def get_client_ip(request: Request, trusted_cidrs: Optional[str] = None) -> str:
    """
    Extract verified client IP from request.
    Only trusts X-Forwarded-For if request.client.host is within TRUSTED_PROXY_CIDRS.
    Otherwise returns request.client.host directly.
    """
    host = request.client.host if request.client else "unknown"
    if host == "unknown":
        return host

    cidrs_str = trusted_cidrs if trusted_cidrs is not None else os.environ.get("TRUSTED_PROXY_CIDRS", "")
    if not cidrs_str or not cidrs_str.strip():
        return host

    trusted_networks = []
    for part in cidrs_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            trusted_networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue

    if not trusted_networks:
        return host

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        return host

    is_trusted = any(host_ip in net for net in trusted_networks)
    if not is_trusted:
        return host

    xff = request.headers.get("X-Forwarded-For")
    if not xff or not xff.strip():
        return host

    raw_ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
    if not raw_ips:
        return host

    # Take the client IP (first non-proxy IP), validate it, and return it.
    for ip_str in raw_ips:
        try:
            parsed_ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not any(parsed_ip in net for net in trusted_networks):
            return ip_str

    # If all valid IPs in XFF were in trusted_networks, return the first valid IP from XFF
    for ip_str in raw_ips:
        try:
            ipaddress.ip_address(ip_str)
            return ip_str
        except ValueError:
            continue

    return host
