# ADR 0006: Dual Authentication Modes (Demo vs Production JWT)

## Status
Accepted

## Context
Development, hackathon demos, and evaluation environments require zero-friction user switching, while production environments demand cryptographically verifiable identities, bearer tokens, and secure credential handling.

## Decision
Support dual authentication modes configured via `AUTH_MODE`:
1. `AUTH_MODE=demo`: Accepts `X-User-Id` header (with fallback to Bearer token). Refuses startup in `APP_ENV=production` unless `ALLOW_DEMO_AUTH=true`.
2. `AUTH_MODE=jwt`: Enforces `Authorization: Bearer <token>` on protected endpoints. Tokens signed via PyJWT with HS256/384/512, requiring `exp` and `sub` claims. Passwords hashed via bcrypt (configurable rounds via `BCRYPT_ROUNDS`). Refuses startup with default or insecure secrets.
3. Login Endpoint `/api/auth/login`: Provides rate-limited credential exchange with constant-time password verification, IP lockout on successive failures, and standardized error responses preventing account enumeration.

## Consequences
- Fast local testing and automated UI demo walkthroughs.
- Secure, production-hardened JWT authentication for deployments.
