from abc import ABC, abstractmethod
import os
import sys
import time
import uuid
import logging
import threading
import ipaddress
from typing import Optional, Dict, List, Any
from fastapi import Request

logger = logging.getLogger("opsdesk.ratelimit")


class RateLimiter(ABC):
    """Abstract base class defining the rate limiter interface."""

    @abstractmethod
    def is_rate_limited(self, key: str, max_requests: int, window_seconds: float) -> bool:
        """
        Check if a given key has exceeded the maximum allowed requests within the time window.
        Returns True if rate limit is exceeded, False otherwise.
        """
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

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: float) -> bool:
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


class RedisRateLimiter(RateLimiter):
    """
    Sliding-window rate limiter backed by Redis.
    Falls back gracefully to InMemoryRateLimiter if Redis is unavailable or uninstalled.
    """

    def __init__(self, redis_client: Optional[Any] = None, redis_url: Optional[str] = None):
        self.redis: Optional[Any] = None
        self.fallback: Optional[InMemoryRateLimiter] = None

        if redis_client is not None:
            self.redis = redis_client
        else:
            try:
                import redis
                url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                client = redis.from_url(url)
                client.ping()
                self.redis = client
            except Exception as exc:
                logger.warning(
                    f"Redis connection failed or redis package not installed: {exc}. "
                    "Falling back to InMemoryRateLimiter."
                )
                self.redis = None
                self.fallback = InMemoryRateLimiter()

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: float) -> bool:
        if self.redis is None:
            if self.fallback is None:
                self.fallback = InMemoryRateLimiter()
            return self.fallback.is_rate_limited(key, max_requests, window_seconds)

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        try:
            # Check pipeline support
            if hasattr(self.redis, "pipeline"):
                try:
                    pipe = self.redis.pipeline()
                    pipe.zremrangebyscore(redis_key, 0, window_start)
                    pipe.zcard(redis_key)
                    res = pipe.execute()
                    current_count = res[1] if isinstance(res, (list, tuple)) and len(res) > 1 else self.redis.zcard(redis_key)
                except Exception:
                    # Direct call fallback
                    self.redis.zremrangebyscore(redis_key, 0, window_start)
                    current_count = self.redis.zcard(redis_key)
            else:
                self.redis.zremrangebyscore(redis_key, 0, window_start)
                current_count = self.redis.zcard(redis_key)

            if current_count >= max_requests:
                return True

            member = f"{now}:{uuid.uuid4().hex}"
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
        except Exception as exc:
            logger.warning(f"Redis operation failed ({exc}), falling back to InMemoryRateLimiter.")
            if self.fallback is None:
                self.fallback = InMemoryRateLimiter()
            return self.fallback.is_rate_limited(key, max_requests, window_seconds)


def get_rate_limiter() -> RateLimiter:
    """Factory function returning the configured RateLimiter implementation."""
    backend = os.environ.get("RATE_LIMIT_BACKEND", "inmemory").lower()
    redis_url = os.environ.get("REDIS_URL")
    if backend == "redis":
        if redis_url:
            limiter = RedisRateLimiter(redis_url=redis_url)
            if limiter.fallback is not None:
                return limiter.fallback
            return limiter
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
