# ADR 0007: Atomic Sliding-Window Rate Limiting with Circuit Breaker

## Status
Accepted

## Context
High-traffic operations endpoints (login authentication, ticket creation, and LLM intent suggestion) are subject to abuse, brute-force attacks, and quota exhaustion. Rate limits must be accurate across multi-process workers without introducing single-point-of-failure outages when external caching infrastructure experiences latency or partition.

## Decision
We implement a unified `RedisRateLimiter` utilizing atomic Redis Lua scripts with an automatic circuit breaker:
1. **Sliding-Window Lua Script:** Evaluates rolling windows using Redis sorted sets (`ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`, `EXPIRE`) atomically within Redis, returning allowed status and remaining quota.
2. **Circuit Breaker:** Tracks consecutive Redis timeouts/failures. Upon 3 consecutive failures, trips open for a configurable cooldown window (`CIRCUIT_COOLDOWN_SEC=15`), immediately falling back to local memory without blocking request threads.
3. **Graceful Fallback Mode:** Configured via `RATE_LIMIT_FAIL_MODE` (`open` or `closed`). Defaults to `open` for operations availability, logging warnings while allowing legitimate agent workflows to proceed.
4. **In-Memory Fallback:** When Redis is unconfigured or partitioned, thread-safe in-memory sliding windows enforce local rate limits (multiplied by worker process count in multi-worker deployments).

## Consequences
- **Positive:** Sub-millisecond atomic rate evaluation across clustered workers; zero downtime during Redis transient drops; defense against credential stuffing and AI quota abuse.
- **Negative:** When running in-memory fallback across $N$ workers, aggregate cluster limit scales to $N \times \text{limit}$.
