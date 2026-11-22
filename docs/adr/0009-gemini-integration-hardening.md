# ADR 0009: Gemini AI Integration Hardening (PII Redaction, Bounds, Observability)

## Status
Accepted

## Context
OpsDesk integrates Gemini Flash via `/api/ai/suggest-intent` for fallback ticket categorization. Sending unredacted customer data to external LLMs introduces privacy compliance risks (GDPR, ISO 27001), while unbounded external calls can cause thread pool exhaustion, latency spikes, and vendor quota throttling.

## Decision
We enforce a multi-layered security and resilience perimeter around Gemini calls:
1. **PII Redaction:** Pre-egress sanitation replaces emails (`[REDACTED_EMAIL]`), phone numbers (`[REDACTED_PHONE]`), URLs (`[REDACTED_URL]`), booking reference tokens (`[REDACTED_REF]`), 6+ digit numbers (`[REDACTED_NUM]`), and traveler names before prompts leave the application boundary.
2. **XML Delimiters:** User input is encapsulated within `<ticket_data>` XML tags to prevent prompt injection and instruction subversion.
3. **Concurrency Bounds:** Dedicated `ThreadPoolExecutor(max_workers=5)` bounds simultaneous external Gemini HTTP calls, protecting FastAPI worker threads.
4. **LRU In-Memory Cache:** Redacted request hashes (SHA-256) are cached in an LRU cache (1,000 items, 1-hour TTL) to eliminate redundant outbound requests.
5. **Observability & Quotas:** Per-user rate limiting (20 req/min) prevents quota exhaustion. Detailed fallback metrics with standard reason codes (`disabled`, `rate_limited`, `timeout`, `api_error`, `circuit_open`) are exposed via authenticated `GET /api/ai/stats` (Lead role only).

## Consequences
- **Positive:** Zero plaintext PII egress; deterministic caching eliminates redundant cost and latency; system remains responsive even during external AI outages.
- **Negative:** Redaction regex rules must be maintained as booking reference formats evolve.
