# Security Policy

## 1. Supported Versions

We provide security updates and patches for the following versions of OpsDesk:

| Version | Supported          | Status |
| ------- | ------------------ | ------ |
| 1.0.x   | :white_check_mark: | Active Development (Milestone 3 Reference Release) |
| < 1.0.0 | :x:                | Deprecated (Pre-release Prototypes) |

---

## 2. Demo Authentication Warning & Production Migration

> [!WARNING]
> **Demo-Only Authentication Notice:**
> The current version of OpsDesk utilizes client-supplied identity (`X-User-Id` header) to facilitate seamless role demonstration across multiple agent profiles (`Agent`, `Lead`, `EscalationManager`, `Requester`), as permitted under the hackathon evaluation specification (*Zendesk-Darwin box Automation.pdf*, Page 6).

### Production Hardening Guidelines
Before deploying OpsDesk to a public or production environment:
1. **Replace Demo Auth:** Replace `get_current_user` in `backend/app/auth.py` with signed cryptographic tokens (OAuth 2.0 / OpenID Connect / JWT bearer tokens).
2. **Database Migration:** Migrate from local SQLite to managed PostgreSQL with row-level tenant security (RLS) and encrypted connections (SSL/TLS).
3. **CORS Restrictions:** Set `ALLOWED_CORS_ORIGINS` to trusted, verified company domains.
4. **Secret Management:** Store all API keys, database credentials, and service tokens in environment variables or an enterprise secret vault (e.g. HashiCorp Vault, AWS Secrets Manager). Never commit `.env` or database files to source control.

---

## 3. Multi-Tenant Agency Isolation

OpsDesk enforces strict multi-agency isolation guarantees:
- **Agency Requesters (`Requester` role):** Restricted strictly to their own agency's tickets (`agency_id`). Any attempt to access, list, or mutate another agency's tickets returns `HTTP 403 Forbidden` or `HTTP 404 Not Found`.
- **Internal Note Privacy:** Internal staff communications (`InternalNote`) and supplier side-threads (`side-threads`) are completely stripped from API responses delivered to `Requester` roles.
- **Queue & Score Privacy:** Triage queue positions, internal priority scores, and routing reasons are withheld from external agency views.

---

## 4. Reporting a Vulnerability

OpsDesk is an open-source hackathon prototype. Vulnerability reporting and triage are handled on a **best-effort, hackathon prototype** basis:

1. **Do NOT open a public GitHub issue for sensitive security exploits.**
2. Report vulnerabilities via GitHub Private Security Advisories on this repository.
3. Include:
   - Description of the vulnerability and affected endpoint/component.
   - Proof of Concept (PoC) or reproducible steps.
   - Potential impact on tenant isolation or data integrity.

---

## 5. Gemini AI Integration & Data Egress Policy

When OpsDesk invokes the external Google Gemini API for ticket intent classification fallback, strict egress controls and data hygiene guarantees are applied:

### Exact Data Transmitted Outside the System
- **Only Sanitized Subject & Body:** Only the ticket's title and description are transmitted, encapsulated inside explicit `<user_message>` boundary delimiters.
- **Classification Taxonomy Schema:** The static list of allowable intent category names and expected JSON schema (`{"suggested_intent": "<CategoryName>", "confidence": <0.0-1.0>}`).

### Data NEVER Transmitted (Strict Zero-Exposure Guarantees)
- **Zero Personally Identifiable Information (PII):** All text is pre-processed through automated regex sanitization:
  - Email addresses are scrubbed and replaced with `[EMAIL]`.
  - Domestic and international phone numbers are replaced with `[PHONE]`.
  - External and internal URLs are replaced with `[URL]`.
  - Sensitive 6+ digit numbers (e.g. credit cards, national IDs, bank accounts) are replaced with `[REDACTED_NUM]`.
  - Booking, PNR, confirmation, and reservation reference tokens are replaced with `[BOOKING_REF]`.
  - Passenger, guest, and customer names following prefixes (`guest`, `Mr.`, `Mrs.`, `Ms.`, `Dr.`) are replaced with `[NAME]`.
- **Zero Passwords or Credentials:** No database credentials, session tokens, JWTs, API secrets, or passwords ever leave the host system.
- **Zero Staff or Supplier Metadata:** Internal notes, supplier side-thread messages, triage urgency scores, agency contracts, and staff identities are never included in prompts.

### Prompt Injection and Concurrency Defenses
- **Boundary Isolation:** User text is framed inside XML tags `<user_message>` with explicit system instructions to ignore prompt injection, role-reversal, or override attempts.
- **Bounded Thread Pool & Concurrency Semaphore:** Outbound API calls run within a bounded `ThreadPoolExecutor` (default 4 workers) governed by a process semaphore and strict 3.0s timeout to prevent thread exhaustion.
- **In-Memory Cryptographic LRU Cache:** Ticket contents are hashed (`SHA-256`) and cached for 1 hour (capacity 1,000 entries), avoiding unnecessary egress calls for identical requests.

