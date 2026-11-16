# ADR 0004: Intent-Aware LCD SLA Deadlines

## Status
Accepted

## Context
Standard B2B helpdesks calculate SLA deadlines strictly from ticket creation time or static priority levels. In travel operations, operational risk is determined by physical travel deadlines:
1. `check_in_date`: Flight departure or hotel check-in time.
2. `lcd_date`: Last Cancellation Date/Time (after which supplier fees or booking penalties become non-refundable).

However, not all intents should prioritize LCD. For example, in an `Emergency Check-in Assist` scenario (traveler stranded at hotel/airport counter), the check-in time is immediate and critical, whereas LCD is moot. Conversely, for `Cancellation & Refund` or `Amendment Request`, the LCD date is the urgent financial boundary.

## Decision
We implement a shared helper `effective_deadline_hours(check_in_date, lcd_date, intent, now_dt)`:
1. If intent is `Emergency Check-in Assist`: LCD is explicitly ignored, and deadline hours are computed solely against `check_in_date`.
2. For all other intents: If `lcd_date` is present and earlier than `check_in_date`, the `lcd_date` acts as the binding effective deadline.
3. Both `evaluate_travel_sla` and queue ranking `calculate_queue_score_tier2` invoke this single shared helper to guarantee consistent deadline evaluations.

## Consequences
- **Positive:** Financial penalty prevention on cancellations, physical passenger safety and check-in prioritization on emergencies.
- **Negative:** Accurate booking metadata (`check_in_date`, `lcd_date`) must be provided by upstream booking systems (TBOH).
