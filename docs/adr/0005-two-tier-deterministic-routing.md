# ADR 0005: Two-Tier Deterministic Queue Routing with Staff-Only Emergency Bypass

## Status
Accepted (Amended in Round 10)

## Context
In a travel operations queue handling 5,000+ concurrent active tickets, dispatchers and regional agents require unambiguous, deterministic ordering of tickets. Simple FIFO processing starves stranded passengers facing immediate flight or check-in deadlines, while static priority sorting ignores imminent supplier cancellation cutoffs (LCD).

Furthermore, public Requester submissions must not be permitted to exploit emergency bypass triggers (e.g. self-assigning high priority or triggering emergency escalation to managerial queues), which would create an operational denial-of-service vector against escalation staff.

## Decision
We enforce a **deterministic two-tier routing engine**:

1. **Tier 1 (Emergency Bypass - Staff Only):**
   - **Eligibility:** Restricted strictly to tickets created by authenticated internal staff (`Agent`, `EscalationManager`, `Lead`). Tickets created by external `Requester` roles are strictly ineligible for emergency bypass.
   - **Condition:** Operational check-in deadline within 4 hours (`0.0 <= effective_deadline_hours <= 4.0`) matching `EMERGENCY_BYPASS_INTENTS`.
   - **Staff Action:** Automatically sets priority to `Urgent`, status to `Escalated`, and assigns the ticket to Escalation Manager (`USR-103`).
   - **Requester Guardrail (Option A):** When a `Requester` creates a ticket with near check-in, priority remains as requested, status remains `New`/`Open`, assignment proceeds to regional agent pools via workload affinity, and routing reason is explicitly annotated: `"Requester ticket: near check-in, review recommended"`. The ticket's queue ranking still ascends smoothly via Tier-2 time modifiers without operational preemption.

2. **Tier 2 (Continuous Dynamic Queue Scoring):**
   - Applies to all non-bypassed operational tickets.
   - Formula:
     $$\text{QueueScore} = (\text{BasePriorityWeight} + \text{TimeModifier}) \times \text{AgencyTierMultiplier}$$
     - Priority Weights: Urgent=1000, High=500, Medium=200, Low=50.
     - Time Urgency Modifiers: $\le 2\text{h}$: +2000, $\le 6\text{h}$: +800, $\le 24\text{h}$: +300, $> 24\text{h}$: 0.
     - Agency Tier Multipliers: Platinum: 1.30x, Gold: 1.15x, Standard: 1.00x.
   - Queue order is deterministically sorted by `queue_score DESC, created_at ASC`.

## Consequences
- **Positive:** Zero starvation for stranded travelers; eliminates managerial queue flooding by public requesters; mathematical ranking verifiable via golden vectors.
- **Negative:** Non-urgent low-priority inquiries experience longer queue residency if high-priority volume remains consistently elevated.
