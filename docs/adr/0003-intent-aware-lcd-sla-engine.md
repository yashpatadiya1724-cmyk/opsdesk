# ADR 0003: Intent-Aware LCD SLA Engine

## Status
Accepted

## Context
Standard helpdesks compute SLA deadlines solely from ticket submission time. In physical travel operations, urgency is driven by physical check-in proximity and Last Cancellation Date (LCD).

## Decision
SLA calculation is intent-aware:
- For cancellation-sensitive intents (`Refund Request`, `Cancellation Inconvenience`, `Unclassified`), effective deadline = `min(check_in_date, lcd_date)`.
- For operational service intents, effective deadline = `check_in_date`.
All timestamps are normalized to timezone-aware UTC via property timezone (`hotel_timezone`).

## Consequences
- Accurate operational countdowns preventing supplier cancellation penalties.
- Deterministic SLA states (`NORMAL`, `AT_RISK`, `BREACHED`, `STOPPED`).
