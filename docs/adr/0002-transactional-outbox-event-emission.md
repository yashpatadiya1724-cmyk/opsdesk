# ADR 0002: Transactional Outbox for Event Emission

## Status
Accepted

## Context
Cross-system synchronization and downstream audit trails require guaranteed event emission without distributed transaction overhead (dual-write problem).

## Decision
All critical lifecycle transitions (ticket creation, status update, priority escalation, messages) write an atomic row to the `events_outbox` table within the same database transaction that updates the ticket. An external worker or CDC process can reliably tail this table.

## Consequences
- Guaranteed at-least-once event delivery semantics.
- Tenant visibility partitioning (`public` vs `internal`) baked directly into the event payload.
- No network timeouts or messaging broker failures can roll back ticket creation.
