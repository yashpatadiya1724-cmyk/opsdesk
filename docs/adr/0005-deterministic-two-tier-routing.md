# ADR 0005: Deterministic Two-Tier Queue Routing

## Status
Accepted

## Context
In a travel support queue with 5,000+ active tickets, operations dispatchers must instantly know which ticket to process next without guessing. Simple FIFO queues fail because urgent travel departures are starved, while pure priority-based sorting ignores nearing deadlines.

## Decision
We enforce a **deterministic two-tier routing engine**:
1. **Tier 1 (Emergency Bypass):**
   - Condition: Check-in deadline < 4 hours (`effective_deadline_hours < 4.0`).
   - Behavior: Automatically jumps to the top of the queue with priority `Urgent` and status `Escalated`, sorted by earliest deadline ascending.
2. **Tier 2 (Continuous Dynamic Scoring):**
   - Applies to all other operational tickets.
   - Formula:
     $$\text{Score} = \text{BasePriority} + \text{DeadlineUrgencyScore} + \text{AgencyWeight}$$
     where deadline urgency score is inversely proportional to `effective_deadline_hours` (capped at 48h horizon), augmented by agency tier multipliers.
   - Result is deterministically sorted descending by queue score.

## Consequences
- **Positive:** Guaranteed zero starvation for stranded travelers; transparent mathematical ranking verifiable via golden vectors.
- **Negative:** Non-urgent low-priority inquiries can experience prolonged queue residency if high-priority volume remains consistently elevated.
