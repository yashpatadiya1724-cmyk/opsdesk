# ADR 0002: Transactional Outbox Pattern for Decoupled Sidecars

## Status
Accepted

## Context
When ticket status updates, new messages arrive, or SLA deadlines approach, connected operator dashboards must receive notifications. Directly dispatching webhooks or message queue events inside HTTP request handlers causes dual-write hazards: the database write can succeed while message dispatch fails, or vice-versa.

## Decision
We implement the **Transactional Outbox Pattern** using an `events_outbox` table:
1. Every state mutation (ticket create, update, transfer, message creation) commits both the business entity and an outbox event in the same ACID database transaction.
2. The `events_outbox` record captures event type, ticket ID, agency ID, visibility (`public` vs `internal`), and a JSON payload.
3. Decoupled consumers (e.g. Go SSE daemon or background workers) poll or stream from `events_outbox` and mark `delivered_at` upon transmission.

## Consequences
- **Positive:** Guaranteed at-least-once event delivery, zero dual-write inconsistencies, complete audit trail of state events.
- **Negative:** Requires background worker polling or Change Data Capture (CDC) to dispatch outbox records.
