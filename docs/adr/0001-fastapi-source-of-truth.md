# ADR 0001: FastAPI as Single Source of Truth

## Status
Accepted

## Context
OpsDesk manages high-concurrency B2B travel operations involving multi-tenant agency data, audit logging, and strict state transitions. The system requires sidecars for specialized tasks (e.g. streaming export, SSE realtime broadcasting), creating a risk of data drift, split-brain validation, and duplicated authorization logic across language boundaries.

## Decision
We designate the Python FastAPI service as the **exclusive Single Source of Truth** for all operations:
1. **State Mutation & Validation:** Only FastAPI endpoints write to core tables (`tickets`, `ticket_messages`, `side_conversations`, `audit_logs`, `events_outbox`).
2. **Access Control:** All RBAC and agency-scoping rules are evaluated and enforced strictly within FastAPI request dependencies.
3. **Reference Implementations:** All computational logic (SLA calculation, routing algorithms, intent taxonomy matching) has a complete, standalone Python implementation that functions without external sidecars.

## Consequences
- **Positive:** Centralized audit logs, zero schema drift between languages, straightforward local development without requiring Go or Rust toolchains.
- **Negative:** Highly CPU-intensive scoring across tens of thousands of records requires Python optimization or offloading to verified sidecars.
