# ADR 0008: Stored Queue Score Cache with Selective Boundary Refresh and pg_trgm

## Status
Accepted

## Context
At 10,000+ active tickets, calculating dynamic Tier-2 queue scores on every `GET /api/tickets` request via complex SQL CASE expressions causes full table scans and high CPU utilization. At the same time, periodic batch updates across all active rows cause high database write amplification, WAL churn, and lock contention.

## Decision
We implement a hybrid stored score architecture:
1. **Materialized Column:** Add `tickets.queue_score` (Float) populated at ticket creation and state transition time.
2. **Composite Index:** Create `ix_tickets_status_assigned_score` on `(status, assigned_to, queue_score)` to turn queue retrieval and pagination into an index-only or index-range scan.
3. **Selective Refresher:** Background task `refresh_stale_queue_scores(db)` runs at 30-second intervals. It computes the 2h, 6h, and 24h urgency boundary transitions and updates only tickets that have crossed boundary thresholds since their last update. The staleness bound is strictly $\le 30$ seconds.
4. **PostgreSQL Trigram Search:** For PostgreSQL deployments, migration `0004_stored_queue_score_and_trigram` enables `pg_trgm` extension and creates GIN indexes `ix_tickets_title_trgm` and `ix_tickets_customer_name_trgm` to accelerate free-text substring searches. Dialect guards skip pg_trgm on SQLite.

## Consequences
- **Positive:** Query time for 10,000 tickets drops from >120ms to <1.5ms; zero table-wide lock contention; boundary-only writes minimize database write volume.
- **Negative:** Queue scores have a maximum staleness bound of 30 seconds for tickets residing between boundary thresholds.
