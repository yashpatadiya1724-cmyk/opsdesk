# ADR 0004: Two-Tier Deterministic Routing with Dynamic Queue Ordering

## Status
Accepted

## Context
Tickets must be assigned to the most qualified agent without manual dispatch bottleneck, while emergency cases must bypass queues immediately.

## Decision
- **Tier 1 (Agent Selection & Emergency Bypass):**
  - If effective deadline <= 4 hours, trigger Tier-1 Emergency Bypass (priority forced to `Urgent`, status `Escalated`, routed to Escalation Manager `USR-103`).
  - Standard assignment matches agent availability, regional affinity (country-to-hub), and lowest active workload.
- **Tier 2 (Queue Ordering):**
  - Read-time dynamic queue scoring inside SQL `ORDER BY` using CASE expression:
    `(priority_weight + time_modifier) * tier_multiplier`.
    - Priority scores: Urgent=1000, High=500, Medium=200, Low=50.
    - Urgency modifiers: <=2h: 2000, <=6h: 800, <=24h: 300, >24h: 0.
    - Tier multipliers: Platinum: 1.3x, Gold: 1.15x, Standard: 1.0x.
  - Zero writes on GET requests.

## Consequences
- Eliminates write-on-read lock contention.
- Guarantees exact, real-time priority ordering across changing wall-clock time.
