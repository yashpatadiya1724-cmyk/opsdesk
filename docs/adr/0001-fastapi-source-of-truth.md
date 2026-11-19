# ADR 0001: FastAPI Source of Truth for Operations Platform

## Status
Accepted

## Context
OpsDesk serves as the single source of truth for B2B travel operations, requiring high-throughput async and sync capabilities, automatic OpenAPI schema generation, and strict role-based access control.

## Decision
FastAPI with SQLAlchemy ORM and Pydantic validation acts as the definitive operational backend. All state mutations, validations, idempotency checks, and audit logging happen centrally in this service.

## Consequences
- Clean RESTful contract with auto-generated OpenAPI documentation.
- Direct database connection pooling supporting SQLite (WAL mode) and PostgreSQL.
- Eliminates external dependencies for basic core operational workflows.
