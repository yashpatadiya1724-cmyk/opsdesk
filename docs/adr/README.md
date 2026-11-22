# Architecture Decision Records (ADRs)

This directory documents the key architectural and design decisions for OpsDesk. Each record outlines the context, decision, and consequences of a significant architectural choice.

| ADR | Title | Status | Summary |
| --- | ----- | ------ | ------- |
| [0001](0001-fastapi-source-of-truth.md) | FastAPI Source of Truth | Accepted | Single source of truth with SQLAlchemy ORM and Pydantic validation for operations. |
| [0002](0002-transactional-outbox.md) | Transactional Outbox Pattern | Accepted | Atomic outbox events inside ticket transactions to eliminate dual-write hazards. |
| [0003](0003-rule-first-intent-classification.md) | Rule-First Intent Classification | Accepted | Deterministic regex matching first with bounded LLM fallback for ~5% unclassified tickets. |
| [0004](0004-intent-aware-lcd-sla.md) | Intent-Aware LCD SLA Deadlines | Accepted | Effective deadline calculated as $\min(\text{check-in}, \text{LCD})$ for cancellations, or check-in for emergencies. |
| [0005](0005-two-tier-deterministic-routing.md) | Two-Tier Deterministic Queue Routing | Accepted | Staff-only Tier-1 Emergency Bypass; mathematical Tier-2 scoring for operational tickets. |
| [0006](0006-dual-authentication-modes.md) | Dual Authentication Modes | Accepted | Demo header-based auth for testing and evaluation; production JWT bearer tokens with bcrypt hashing. |
| [0007](0007-sliding-window-rate-limiting.md) | Atomic Sliding-Window Rate Limiting | Accepted | Redis Lua sliding window with circuit breaker and graceful in-memory fallback. |
| [0008](0008-stored-queue-score-and-selective-refresh.md) | Stored Queue Score & Refresher | Accepted | Materialized indexed `queue_score` with 30s selective boundary refresh and pg_trgm. |
| [0009](0009-gemini-integration-hardening.md) | Gemini Integration Hardening | Accepted | PII pre-redaction, XML boundaries, bounded executor pool, LRU cache, and stats endpoint. |
