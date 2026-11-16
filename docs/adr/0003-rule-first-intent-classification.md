# ADR 0003: Rule-First Intent Classification with LLM Fallback

## Status
Accepted

## Context
OpsDesk processes high volumes of incoming support tickets from travel agencies. Automated intent tagging is essential for SLA calculation and queue prioritization. However, relying entirely on remote LLM API calls introduces latency (500ms-2000ms), external network failure risks, and non-deterministic classifications for well-known travel patterns.

## Decision
We implement a **two-stage hybrid intent classification engine**:
1. **Deterministic Rule Engine (First Line of Defense):** A regex-based pattern matcher executes against ticket title and description, mapping standard travel terminology (e.g. check-in issues, cancellations, refunds, rebooking) to the fixed `INTENT_TAXONOMY` (confidence: 1.0).
2. **LLM Fallback (Second Line of Defense):** When rule matching returns no confident match, the ticket is classified as `Unclassified` (or optionally routed to Gemini Flash via `/api/ai/suggest-intent` with temperature 0.0 and JSON schema enforcement).
3. **Guardrail:** The seeded distribution regulates `Unclassified` tickets to approximately ~5% (below the 15% operational ceiling).

## Consequences
- **Positive:** Sub-millisecond classification for 95%+ of routine tickets, zero LLM token cost for standard queries, 100% deterministic SLA assignment.
- **Negative:** New travel operational terms require regex pattern maintenance and taxonomy updates.
