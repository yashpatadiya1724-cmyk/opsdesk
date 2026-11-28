import asyncio
import uuid
import csv
import io
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, defer
from sqlalchemy import desc, func, or_, text

from backend.app.database import get_db
from backend.app.models import (
    User, Agency, Ticket, TicketLink, TicketMessage,
    SideConversation, SideConversationRecipient, SideConversationMessage,
    TicketTheme, EventOutbox, AuditLog, IdempotencyRecord
)
from backend.app.schemas import (
    TicketCreateSchema, TicketAssignSchema, TicketStatusUpdateSchema,
    TicketEscalateSchema, TicketTransferSchema, TicketLinkSuggestionSchema, MessageCreateSchema,
    SideThreadCreateSchema, SideThreadMessageCreateSchema,
    IntentSuggestRequestSchema, IntentSuggestResponseSchema, to_utc_aware,
    LoginRequest, LoginResponse, AgencyTierUpdateSchema,
    BulkAssignRequestSchema, BulkStatusUpdateSchema
)
from backend.app.auth import (
    get_current_user, verify_password, create_access_token,
    DEFAULT_JWT_SECRET, DEFAULT_JWT_ALGORITHM, ALLOWED_JWT_ALGORITHMS,
    is_production, get_bcrypt_rounds
)
from backend.app.events import emit_outbox_event, record_audit_log, get_broadcaster
from backend.config.routing_config import (
    DEFAULT_ESCALATION_MANAGER_ID,
    REGION_MAPPING,
    EMERGENCY_BYPASS_HOURS,
    EMERGENCY_BYPASS_INTENTS,
    PRIORITY_SCORES
)
from backend.services.sla_engine import evaluate_travel_sla, effective_deadline_hours
from backend.services.routing_engine import (
    CandidateAgent, select_agent_tier1, calculate_queue_score_tier2,
    compute_ticket_urgency_fields, refresh_stale_queue_scores,
    get_sql_queue_score_expr, compute_ticket_queue_score
)
from backend.services.intent_classifier import suggest_ticket_intent, get_ai_stats

import os
import time
import logging
import threading
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from backend.app.rate_limiter import (
    RateLimiter, InMemoryRateLimiter, RedisRateLimiter, get_rate_limiter, get_client_ip
)

logger = logging.getLogger("opsdesk.access")
logging.basicConfig(level=logging.INFO)

_START_TIME = time.time()

app = FastAPI(
    title="OpsDesk: B2B Travel Operations Case Management API",
    description="Operational case management platform tailored for high-volume B2B travel operations.",
    version="1.0.0"
)

cors_origins_env = os.environ.get(
    "ALLOWED_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100"
)
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Next-Cursor", "X-Request-ID"],
)


class RequestBodySizeLimitMiddleware:
    """
    Enforces maximum request body size (MAX_BODY_BYTES, default 1MB).
    Checks Content-Length header, and monitors streamed request body chunks.
    Returns 413 Payload Too Large if size limit is exceeded.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            max_bytes = int(os.environ.get("MAX_BODY_BYTES", "1048576"))
        except (ValueError, TypeError):
            max_bytes = 1048576

        headers = dict(scope.get("headers", []))
        cl_bytes = headers.get(b"content-length")
        path = scope.get("path", "")
        security_headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-frame-options", b"DENY"),
        ]
        if path.startswith("/api/"):
            security_headers.append((b"cache-control", b"no-store"))

        if cl_bytes:
            try:
                cl = int(cl_bytes)
                if cl > max_bytes:
                    body = json.dumps({"detail": f"Payload Too Large: {cl} bytes exceeds maximum allowed {max_bytes} bytes"}).encode("utf-8")
                    res_headers = [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("utf-8")),
                    ] + security_headers
                    await send({
                        "type": "http.response.start",
                        "status": 413,
                        "headers": res_headers,
                    })
                    await send({
                        "type": "http.response.body",
                        "body": body,
                    })
                    return
            except ValueError:
                pass

        total_bytes = 0

        async def limited_receive():
            nonlocal total_bytes
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Payload Too Large: body exceeded maximum allowed {max_bytes} bytes"
                    )
            return message

        try:
            await self.app(scope, limited_receive, send)
        except HTTPException as exc:
            if exc.status_code == 413:
                body = json.dumps({"detail": exc.detail}).encode("utf-8")
                res_headers = [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("utf-8")),
                ] + security_headers
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": res_headers,
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
            else:
                raise


app.add_middleware(RequestBodySizeLimitMiddleware)

RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
RATE_LIMIT_MAX_KEYS = int(os.environ.get("RATE_LIMIT_MAX_KEYS", "10000"))
RATE_LIMIT_WINDOW = 60.0  # seconds

RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE = int(os.environ.get("RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE", "10"))
RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR = int(os.environ.get("RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR", "100"))

IDEMPOTENCY_TTL_HOURS = int(os.environ.get("IDEMPOTENCY_TTL_HOURS", "24"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
ALLOW_DEMO_AUTH = os.environ.get("ALLOW_DEMO_AUTH", "false").lower() in ("true", "1", "yes")

_rate_limiter: RateLimiter = get_rate_limiter()
_rate_limit_lock = getattr(_rate_limiter, "_lock", None)
if _rate_limit_lock is None:
    _rate_limit_lock = threading.Lock()
_rate_limit_records: Dict[str, List[float]] = getattr(_rate_limiter, "_records", None)
if _rate_limit_records is None:
    _rate_limit_records = {}


def validate_production_auth_settings():
    """
    Refuses startup when:
    1. JWT_ALGORITHM is not one of the allowed HMAC algorithms (HS256, HS384, HS512).
    2. Running in AUTH_MODE=jwt and JWT_SECRET is empty, shorter than 32 characters, or equal to DEFAULT_JWT_SECRET.
    3. Running in production environment with demo authentication, unless explicitly overridden via ALLOW_DEMO_AUTH=true.
    """
    auth_mode = os.environ.get("AUTH_MODE", "demo").lower()
    allow_demo = os.environ.get("ALLOW_DEMO_AUTH", "false").lower() in ("true", "1", "yes")
    jwt_secret = os.environ.get("JWT_SECRET", "")
    jwt_algorithm = os.environ.get("JWT_ALGORITHM", DEFAULT_JWT_ALGORITHM)

    if jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
        msg = f"Startup refused: Invalid JWT_ALGORITHM '{jwt_algorithm}'. Allowed algorithms are: {', '.join(sorted(ALLOWED_JWT_ALGORITHMS))}."
        logger.error(msg)
        raise RuntimeError(msg)

    if auth_mode == "jwt":
        if not jwt_secret or len(jwt_secret.strip()) < 32 or jwt_secret == DEFAULT_JWT_SECRET:
            msg = f"Startup refused: In AUTH_MODE=jwt, JWT_SECRET must be explicitly configured, at least 32 characters long, and cannot be the default insecure key (got {len(jwt_secret.strip()) if jwt_secret else 0} chars)."
            logger.error(msg)
            raise RuntimeError(msg)

    if is_production():
        # Enforce secure bcrypt rounds in production
        try:
            get_bcrypt_rounds()
        except ValueError as e:
            logger.error(str(e))
            raise RuntimeError(f"Startup refused: {e}")

        if auth_mode == "demo" and not allow_demo:
            msg = "Production environment requires AUTH_MODE=jwt unless ALLOW_DEMO_AUTH=true (Refusing to start in APP_ENV=production with unauthenticated demo headers)."
            logger.error(msg)
            raise RuntimeError(msg)
        elif allow_demo:
            logger.warning("WARNING: APP_ENV=production is running with demo authentication because ALLOW_DEMO_AUTH=true is set. Ensure this is intentional!")


def purge_expired_idempotency_records(db: Session) -> int:
    """
    Assumption: Purges in-database idempotency records older than IDEMPOTENCY_TTL_HOURS (default 24).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    deleted = db.query(IdempotencyRecord).filter(IdempotencyRecord.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted


_score_refresher_task = None


async def _score_refresher_worker():
    """
    In-process background task that refreshes stale queue scores across tickets.
    Bounded staleness guarantee: Stored scores reflect time urgency within at most 30 seconds
    (the background refresher run interval).
    """
    interval = float(os.getenv("SCORE_REFRESHER_INTERVAL", "30"))
    while True:
        try:
            await asyncio.sleep(interval)
            from backend.app.database import SessionLocal
            with SessionLocal() as db:
                refreshed = refresh_stale_queue_scores(db)
                if refreshed > 0:
                    logger.info(json.dumps({"event": "score_refresher_run", "refreshed": refreshed}))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"Error in score_refresher_worker: {exc}")


@app.on_event("startup")
async def on_app_startup():
    global _score_refresher_task
    validate_production_auth_settings()
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from backend.app.database import SessionLocal, engine, ensure_schema_migrations
            ensure_schema_migrations(engine)
            with SessionLocal() as db:
                purged = purge_expired_idempotency_records(db)
                if purged > 0:
                    logger.info(json.dumps({"event": "idempotency_startup_purge", "purged": purged}))
        except Exception as exc:
            logger.warning(f"Startup maintenance warning: {exc}")

        score_refresher_enabled = os.getenv("SCORE_REFRESHER_ENABLED", "true").lower() in ("true", "1", "yes")
        if score_refresher_enabled:
            _score_refresher_task = asyncio.create_task(_score_refresher_worker())


@app.on_event("shutdown")
async def on_app_shutdown():
    global _score_refresher_task
    if _score_refresher_task and not _score_refresher_task.done():
        _score_refresher_task.cancel()
        try:
            await _score_refresher_task
        except asyncio.CancelledError:
            pass

@app.middleware("http")
async def opsdesk_protection_middleware(request: Request, call_next):
    raw_request_id = request.headers.get("X-Request-ID")
    request_id = raw_request_id if raw_request_id else str(uuid.uuid4())
    start_time = time.time()

    # Rate limiting check:
    # Must NOT use client-supplied X-User-Id header as a bucket key before authentication.
    # Before auth, key strictly on ip:{client_ip}.
    # After authentication (e.g. if user is authenticated via JWT), key on user:{user_id}.
    if request.url.path not in ["/health", "/ready", "/docs", "/openapi.json"]:
        authenticated_user_id = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            try:
                from backend.app.auth import decode_access_token
                payload = decode_access_token(token)
                authenticated_user_id = payload.get("sub")
            except Exception:
                authenticated_user_id = None

        if authenticated_user_id:
            rate_limit_key = f"user:{authenticated_user_id}"
        else:
            client_ip = get_client_ip(request)
            rate_limit_key = f"ip:{client_ip}"

        if _rate_limiter.is_rate_limited(rate_limit_key, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_WINDOW):
            logger.warning(
                json.dumps({
                    "event": "rate_limited",
                    "key": rate_limit_key,
                    "request_id": request_id,
                    "path": request.url.path
                })
            )
            headers = {
                "Retry-After": "60",
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            }
            if request.url.path.startswith("/api/"):
                headers["Cache-Control"] = "no-store"

            return Response(
                content=json.dumps({"detail": "Rate limit exceeded. Please retry later."}),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers=headers
            )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            json.dumps({
                "event": "request_error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration_ms, 2),
                "error": str(exc)
            })
        )
        raise exc

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"

    logger.info(
        json.dumps({
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2)
        })
    )
    return response

# Allowed status transitions graph. Any invalid transition yields 409 Conflict.
ALLOWED_STATUS_TRANSITIONS: Dict[str, List[str]] = {
    "New": ["Open", "Pending", "Escalated", "Closed"],
    "Open": ["Pending", "Escalated", "Resolved", "Closed"],
    "Pending": ["Open", "Escalated", "Resolved", "Closed"],
    "Escalated": ["Open", "Pending", "Resolved", "Closed"],
    "Resolved": ["Open", "Closed"],
    "Closed": []  # Closed is terminal in this workflow
}


# ============================================================================
# 1. AI INTENT SUGGESTION ENDPOINT
# ============================================================================

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "opsdesk-backend"}


@app.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Deep readiness probe checking database connection, pool, rate limiter, and triage queue state."""
    try:
        db.execute(text("SELECT 1"))
        limiter_status = getattr(_rate_limiter, "status", "fallback")
        dialect_name = db.bind.dialect.name if db.bind else "unknown"

        pool = getattr(db.bind, "pool", None)
        pool_info = {
            "size": pool.size() if pool and hasattr(pool, "size") else 0,
            "checked_out": pool.checkedout() if pool and hasattr(pool, "checkedout") else 0,
            "overflow": pool.overflow() if pool and hasattr(pool, "overflow") else 0
        }

        unassigned_count = (
            db.query(func.count(Ticket.id))
            .filter(Ticket.assigned_to.is_(None), Ticket.status.in_(["New", "Open", "Pending"]))
            .scalar() or 0
        )

        return {
            "status": "ready",
            "database": "connected",
            "database_dialect": dialect_name,
            "database_pool": pool_info,
            "rate_limiter": limiter_status,
            "active_subscribers": get_broadcaster().active_subscribers_count,
            "triage_queue": {
                "unassigned_active": unassigned_count
            },
            "uptime_seconds": round(time.time() - _START_TIME, 2)
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: Database probe failed ({str(exc)})"
        )


@app.get("/metrics")
def prometheus_metrics(db: Session = Depends(get_db)):
    """
    Exposes Prometheus-formatted operational telemetry metrics.
    Scraped by Prometheus / Datadog / Grafana agent.
    """
    status_counts = (
        db.query(Ticket.status, Ticket.agency_id, func.count(Ticket.id))
        .group_by(Ticket.status, Ticket.agency_id)
        .all()
    )

    unassigned_count = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.assigned_to.is_(None), Ticket.status.in_(["New", "Open", "Pending", "Escalated"]))
        .scalar() or 0
    )

    subscribers_count = get_broadcaster().active_subscribers_count
    pool = getattr(db.bind, "pool", None)
    pool_size = pool.size() if pool and hasattr(pool, "size") else 0
    pool_checked_out = pool.checkedout() if pool and hasattr(pool, "checkedout") else 0
    pool_overflow = pool.overflow() if pool and hasattr(pool, "overflow") else 0

    lines = [
        "# HELP opsdesk_tickets_total Gauge of tickets by status and agency",
        "# TYPE opsdesk_tickets_total gauge"
    ]
    for st, ag, cnt in status_counts:
        lines.append(f'opsdesk_tickets_total{{status="{st}",agency="{ag}"}} {cnt}')

    lines.extend([
        "# HELP opsdesk_triage_unassigned_total Gauge of unassigned active tickets in triage queue",
        "# TYPE opsdesk_triage_unassigned_total gauge",
        f"opsdesk_triage_unassigned_total {unassigned_count}",
        "# HELP opsdesk_sse_subscribers_active Active real-time SSE listener connections",
        "# TYPE opsdesk_sse_subscribers_active gauge",
        f"opsdesk_sse_subscribers_active {subscribers_count}",
        "# HELP opsdesk_db_pool_size Configured database connection pool size",
        "# TYPE opsdesk_db_pool_size gauge",
        f"opsdesk_db_pool_size {pool_size}",
        "# HELP opsdesk_db_pool_checked_out Currently checked-out connections from pool",
        "# TYPE opsdesk_db_pool_checked_out gauge",
        f"opsdesk_db_pool_checked_out {pool_checked_out}",
        "# HELP opsdesk_db_pool_overflow Currently overflowing connections",
        "# TYPE opsdesk_db_pool_overflow gauge",
        f"opsdesk_db_pool_overflow {pool_overflow}",
        "# HELP opsdesk_uptime_seconds Seconds since backend server process start",
        "# TYPE opsdesk_uptime_seconds counter",
        f"opsdesk_uptime_seconds {round(time.time() - _START_TIME, 2)}"
    ])

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )


RATE_LIMIT_AI_SUGGEST_USER_PER_MINUTE = int(os.environ.get("RATE_LIMIT_AI_SUGGEST_USER_PER_MINUTE", "20"))


@app.post("/api/ai/suggest-intent", response_model=IntentSuggestResponseSchema)
def api_suggest_intent(
    payload: IntentSuggestRequestSchema,
    current_user: User = Depends(get_current_user)
):
    """Suggests an operations intent category based on regex rules or fallback."""
    try:
        user_ai_limit = int(os.environ.get("RATE_LIMIT_AI_SUGGEST_USER_PER_MINUTE", str(RATE_LIMIT_AI_SUGGEST_USER_PER_MINUTE)))
    except (ValueError, TypeError):
        user_ai_limit = 20

    if _rate_limiter.is_rate_limited(f"ai_suggest:user:{current_user.id}", user_ai_limit, 60.0):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: too many AI intent suggestions requested",
            headers={"Retry-After": "60"}
        )

    intent, source = suggest_ticket_intent(payload.title, payload.description)
    return {"intent": intent, "source": source}


@app.get("/api/ai/stats")
def api_get_ai_stats(
    current_user: User = Depends(get_current_user)
):
    """Returns aggregated AI intent suggestion statistics and fallback metrics. Restricted to Lead role."""
    if current_user.role != "Lead":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: AI stats view is restricted to Lead role"
        )
    return get_ai_stats()


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/auth/login", response_model=LoginResponse)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates user with email and password, returning a JWT access token.
    Enforces dedicated failure rate limiter buckets:
    - Per lower-cased email: 5 failures / 15 minutes (900 seconds)
    - Per client IP: 20 failures / 15 minutes (900 seconds)
    Raises 401 Unauthorized if invalid credentials.
    """
    cleaned_email = payload.email.strip().lower()
    client_ip = get_client_ip(request)

    email_bucket = f"login_fail:email:{cleaned_email}"
    ip_bucket = f"login_fail:ip:{client_ip}"

    # Check failure rate limit buckets (5 failures per email, 20 per IP in 900s)
    if _rate_limiter.check_rate_limited(email_bucket, 5, 900.0) or _rate_limiter.check_rate_limited(ip_bucket, 20, 900.0):
        return Response(
            content=json.dumps({"detail": "Rate limit exceeded. Please retry later."}),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            media_type="application/json",
            headers={
                "Retry-After": "900",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-store",
            }
        )

    user = db.query(User).filter(func.lower(User.email) == cleaned_email).first()
    valid = False
    if user and user.hashed_password:
        valid = verify_password(payload.password, user.hashed_password)

    if not valid:
        _rate_limiter.record_event(email_bucket, 900.0)
        _rate_limiter.record_event(ip_bucket, 900.0)
        logger.warning(
            json.dumps({
                "event": "login_failed",
                "email": cleaned_email,
                "client_ip": client_ip
            })
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success resets the email failure bucket
    _rate_limiter.reset(email_bucket)

    try:
        jwt_expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))
    except ValueError:
        jwt_expire_minutes = 480
    expires_in_seconds = jwt_expire_minutes * 60

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.name
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in_seconds
    }


def _resolve_sse_user(
    token: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db)
) -> User:
    auth_header = authorization or (f"Bearer {token}" if token else None)
    demo_user = x_user_id or user_id
    return get_current_user(authorization=auth_header, x_user_id=demo_user, db=db)


@app.get("/api/events/stream")
async def sse_event_stream(
    request: Request,
    current_user: User = Depends(_resolve_sse_user)
):
    """
    Server-Sent Events (SSE) real-time streaming endpoint for live ticket dispatch & operations.
    Pushes ticket lifecycle events (created, assigned, status changed, escalated, messages)
    with strict multi-tenant agency isolation.
    """
    broadcaster = get_broadcaster()
    subscriber = await broadcaster.subscribe(
        user_id=current_user.id,
        agency_id=current_user.agency_id,
        role=current_user.role
    )

    async def event_generator():
        try:
            init_data = json.dumps({
                "status": "connected",
                "user_id": current_user.id,
                "role": current_user.role,
                "agency_id": current_user.agency_id
            })
            yield f"event: connected\ndata: {init_data}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(subscriber.queue.get(), timeout=15.0)
                    evt_type = event_data.get("event", "message")
                    payload_str = json.dumps(event_data)
                    yield f"event: {evt_type}\ndata: {payload_str}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
        finally:
            await broadcaster.unsubscribe(subscriber)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


# ============================================================================
# 2. TICKETS ENDPOINTS
# ============================================================================

@app.get("/api/tickets")
def list_tickets(
    view: str = Query("triage", description="View filter: triage, my_queue, by_region, by_intent, linked"),
    intent: Optional[str] = Query(None, description="Optional intent category filter"),
    priority: Optional[str] = Query(None, description="Optional priority filter (Low, Medium, High, Urgent)"),
    status: Optional[str] = Query(None, description="Optional status filter (New, Open, Pending, Escalated, Resolved, Closed)"),
    search: Optional[str] = Query(None, description="Keyword search across tboh_id, id, and title"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists tickets with computed travel SLA countdown and Tier-2 queue scores.
    Requesters are strictly confined to their own agency.
    Returns the real total count matching query criteria prior to limit pagination.
    """
    query = db.query(Ticket)

    # Apply global search and granular attribute filters
    if priority:
        query = query.filter(Ticket.priority == priority)
    if status:
        query = query.filter(Ticket.status == status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Ticket.tboh_id.ilike(term),
                Ticket.id.ilike(term),
                Ticket.title.ilike(term)
            )
        )

    # Multi-tenant isolation: Requesters only ever see tickets belonging to their own agency
    if current_user.role == "Requester":
        query = query.filter(Ticket.agency_id == current_user.agency_id)
        if view == "linked":
            # Linked tickets strictly within this requester's agency
            agency_ticket_ids = db.query(Ticket.id).filter(Ticket.agency_id == current_user.agency_id)
            linked_ids = db.query(TicketLink.ticket_id).filter(
                TicketLink.ticket_id.in_(agency_ticket_ids),
                TicketLink.linked_ticket_id.in_(agency_ticket_ids)
            ).union(
                db.query(TicketLink.linked_ticket_id).filter(
                    TicketLink.ticket_id.in_(agency_ticket_ids),
                    TicketLink.linked_ticket_id.in_(agency_ticket_ids)
                )
            )
            query = query.filter(Ticket.id.in_(linked_ids))
        elif view == "by_intent":
            if intent:
                query = query.filter(Ticket.intent == intent)
    else:
        # Internal Staff views
        if view == "my_queue":
            query = query.filter(
                Ticket.assigned_to == current_user.id,
                Ticket.status.in_(["New", "Open", "Pending", "Escalated"])
            )
        elif view == "by_region":
            # Filter tickets where the agency country matches user's region
            regional_countries = [c for c, r in REGION_MAPPING.items() if r == current_user.region]
            if regional_countries:
                query = query.join(Agency).filter(Agency.country_code.in_(regional_countries))
            else:
                query = query.join(Agency)
        elif view == "linked":
            # Linked tickets across system
            linked_query = db.query(TicketLink.ticket_id).union(db.query(TicketLink.linked_ticket_id))
            query = query.filter(Ticket.id.in_(linked_query))
        elif view == "by_intent":
            if intent:
                query = query.filter(Ticket.intent == intent)
        elif view == "triage":
            # Active queue: strictly unassigned active tickets (unless an explicit search term is provided)
            if not (search and search.strip()):
                query = query.filter(
                    Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
                    Ticket.assigned_to.is_(None)
                )

    now = datetime.now(timezone.utc)
    if view in ["triage", "my_queue"]:
        query = query.order_by(
            Ticket.queue_score.desc(),
            Ticket.effective_deadline_at.asc(),
            Ticket.id.asc()
        )
    elif view == "by_intent":
        query = query.order_by(
            Ticket.intent.asc(),
            Ticket.created_at.desc(),
            Ticket.id.asc()
        )
    else:
        query = query.order_by(
            Ticket.created_at.desc(),
            Ticket.id.asc()
        )

    # Zero writes on read: no refresh_stale_queue_scores called on GET!

    total_count = query.count()
    tickets = query.options(defer(Ticket.description)).offset(offset).limit(limit).all()

    agency_map = {}
    if current_user.role != "Requester":
        agency_ids = {t.agency_id for t in tickets if t.agency_id}
        if agency_ids:
            agency_rows = db.query(Agency.id, Agency.tier).filter(Agency.id.in_(agency_ids)).all()
            agency_map = {r[0]: r[1] for r in agency_rows}

    results = []
    for t in tickets:
        sla = evaluate_travel_sla(
            status=t.status,
            check_in_date=t.check_in_date,
            lcd_date=t.lcd_date,
            priority=t.priority,
            intent=t.intent,
            now=now
        )
        agency_tier = agency_map.get(t.agency_id) if current_user.role != "Requester" else None
        score_val = (
            None
            if current_user.role == "Requester"
            else (
                t.queue_score
                if t.queue_score is not None
                else compute_ticket_queue_score(
                    ticket=t,
                    agency_tier=agency_tier,
                    now=now,
                    user_role=current_user.role,
                )
            )
        )

        results.append({
            "id": t.id,
            "tboh_id": t.tboh_id,
            "agency_id": t.agency_id,
            "title": t.title,
            "intent": t.intent,
            "priority": t.priority,
            "status": t.status,
            "hotel_timezone": t.hotel_timezone or "UTC",
            "check_in_date": t.check_in_date.isoformat(),
            "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
            "assigned_to": t.assigned_to if current_user.role != "Requester" else None,
            "routing_reason": t.routing_reason if current_user.role != "Requester" else None,
            "sla": sla,
            "queue_score": score_val,
            "created_at": t.created_at.isoformat()
        })

    return {"total": total_count, "tickets": results}


@app.post("/api/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreateSchema,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Creates an operations ticket atomically with:
    1. Tenant isolation (agency_id strictly resolved from DB for Requesters).
    2. Intent suggestion.
    3. Contextual TBOH linking of previous cases.
    4. Tier-1 automated routing assignment.
    5. Atomic EventOutbox row emission and AuditLog.
    6. Idempotent request deduplication via Idempotency-Key header.
    """
    # 0. Check idempotency cache with lazy TTL expiration
    # Assumption: In-database SQLite idempotency records are purged based on IDEMPOTENCY_TTL_HOURS (default 24h); in production 24h Redis TTL is used.
    current_payload_hash = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
    if idempotency_key:
        record_id = f"{current_user.id}:{idempotency_key}"
        cutoff = datetime.now(timezone.utc) - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
        existing_record = db.query(IdempotencyRecord).filter(IdempotencyRecord.id == record_id).first()
        if existing_record:
            rec_created = to_utc_aware(existing_record.created_at)
            if rec_created and rec_created < cutoff:
                db.delete(existing_record)
                db.commit()
                existing_record = None
            else:
                if existing_record.request_hash and existing_record.request_hash != current_payload_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Conflict: Idempotency-Key was already used with a different request payload."
                    )
                return json.loads(existing_record.response_json)

    # 1. Strict agency determination
    if current_user.role == "Requester":
        resolved_agency_id = current_user.agency_id
    else:
        if not payload.agency_id:
            raise HTTPException(
                status_code=400,
                detail="agency_id is required for internal staff when creating a ticket"
            )
        resolved_agency_id = payload.agency_id

    agency = db.query(Agency).filter(Agency.id == resolved_agency_id).first()
    if not agency:
        raise HTTPException(status_code=400, detail="Invalid agency_id specified")

    # Rate limiting for ticket creation (per-user and per-agency)
    try:
        user_create_limit = int(os.environ.get("RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE", str(RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE)))
    except (ValueError, TypeError):
        user_create_limit = 10

    if _rate_limiter.is_rate_limited(f"ticket_create:user:{current_user.id}", user_create_limit, 60.0):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: too many tickets created",
            headers={"Retry-After": "60"}
        )

    try:
        agency_create_limit = int(os.environ.get("RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR", str(RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR)))
    except (ValueError, TypeError):
        agency_create_limit = 100

    if _rate_limiter.is_rate_limited(f"ticket_create:agency:{resolved_agency_id}", agency_create_limit, 3600.0):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: too many tickets created",
            headers={"Retry-After": "3600"}
        )

    # 2. Intent suggestion / resolution
    # Client-supplied intent from Requesters is untrusted and ignored; classify server-side.
    if current_user.role == "Requester":
        resolved_intent, _ = suggest_ticket_intent(payload.title, payload.description)
    else:
        resolved_intent = payload.intent
        if not resolved_intent:
            resolved_intent, _ = suggest_ticket_intent(payload.title, payload.description)

    # 3. Tier-1 Routing
    # Find available desk agents
    desk_agents = db.query(User).filter(User.role == "Agent", User.is_available == True).all()
    candidate_agents = []
    for da in desk_agents:
        active_cnt = db.query(Ticket).filter(
            Ticket.assigned_to == da.id,
            Ticket.status.in_(["New", "Open", "Pending", "Escalated"])
        ).count()
        candidate_agents.append(CandidateAgent(
            id=da.id,
            name=da.name,
            region=da.region,
            is_available=da.is_available,
            active_ticket_count=active_cnt
        ))

    assigned_agent_id, routing_reason = select_agent_tier1(
        agency_country_code=agency.country_code,
        candidate_agents=candidate_agents
    )

    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    # Calculate effective deadline hours for Tier-1 Emergency Bypass check
    deadline_hours = effective_deadline_hours(
        check_in_date=payload.check_in_date,
        lcd_date=payload.lcd_date,
        intent=resolved_intent,
        now=now
    )

    priority = payload.priority
    ticket_status = "Open" if assigned_agent_id else "New"
    is_near_checkin = (
        deadline_hours is not None
        and 0.0 <= deadline_hours <= EMERGENCY_BYPASS_HOURS
        and resolved_intent in EMERGENCY_BYPASS_INTENTS
    )
    is_staff = current_user.role in ("Agent", "EscalationManager", "Lead")
    is_emergency_bypass = is_staff and is_near_checkin

    if is_emergency_bypass:
        priority = "Urgent"
        ticket_status = "Escalated"
        routing_reason = (
            f"Tier-1 Emergency Bypass: effective deadline {deadline_hours:.1f}h <= {EMERGENCY_BYPASS_HOURS}h"
        )
        assigned_agent_id = DEFAULT_ESCALATION_MANAGER_ID
    elif current_user.role == "Requester" and is_near_checkin:
        routing_reason = "Requester ticket: near check-in, review recommended"

    new_ticket = Ticket(
        id=ticket_id,
        tboh_id=payload.tboh_id,
        agency_id=resolved_agency_id,
        title=payload.title,
        description=payload.description,
        intent=resolved_intent,
        priority=priority,
        status=ticket_status,
        check_in_date=payload.check_in_date,
        lcd_date=payload.lcd_date,
        hotel_timezone=payload.hotel_timezone or "UTC",
        priority_weight=PRIORITY_SCORES.get(priority, 200.0),
        assigned_to=assigned_agent_id,
        routing_reason=routing_reason,
        created_at=now,
        updated_at=now
    )
    compute_ticket_urgency_fields(new_ticket, agency_tier=agency.tier, now=now)
    db.add(new_ticket)
    db.flush()

    # 4. First-Class TBOH Linkage: Link prior tickets sharing same TBOH
    link_query = db.query(Ticket).filter(
        Ticket.tboh_id == payload.tboh_id,
        Ticket.id != ticket_id
    )
    if current_user.role == "Requester":
        link_query = link_query.filter(Ticket.agency_id == resolved_agency_id)

    prior_tickets = link_query.all()
    for pt in prior_tickets:
        db.add(TicketLink(
            id=f"LNK-{uuid.uuid4().hex[:8].upper()}",
            ticket_id=ticket_id,
            linked_ticket_id=pt.id,
            link_reason=f"Shared TBOH: {payload.tboh_id}"
        ))

    # 5. Atomic Outbox Event & Audit Log
    emit_outbox_event(
        db=db,
        event_type="ticket.created",
        ticket_id=ticket_id,
        agency_id=resolved_agency_id,
        visibility="public",
        payload={
            "ticket_id": ticket_id,
            "tboh_id": payload.tboh_id,
            "status": new_ticket.status,
            "assigned_to": assigned_agent_id,
            "intent": resolved_intent
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket_id,
        actor_id=current_user.id,
        action="ticket.created",
        details={"tboh_id": payload.tboh_id, "agency_id": resolved_agency_id}
    )

    if is_emergency_bypass:
        record_audit_log(
            db=db,
            ticket_id=ticket_id,
            actor_id=current_user.id,
            action="ticket.emergency_bypass",
            details={
                "reason": routing_reason,
                "effective_deadline_hours": deadline_hours,
                "threshold_hours": EMERGENCY_BYPASS_HOURS,
                "priority": "Urgent",
                "status": "Escalated",
                "assigned_to": assigned_agent_id
            }
        )
        db.add(TicketMessage(
            id=f"MSG-{uuid.uuid4().hex[:8].upper()}",
            ticket_id=ticket_id,
            sender_id=None,
            message_type="InternalNote",
            content=f"[Emergency Bypass] {routing_reason}",
            created_at=now
        ))

    response_data = {
        "id": new_ticket.id,
        "tboh_id": new_ticket.tboh_id,
        "agency_id": new_ticket.agency_id,
        "priority": new_ticket.priority,
        "status": new_ticket.status,
        "assigned_to": new_ticket.assigned_to,
        "routing_reason": new_ticket.routing_reason,
        "intent": new_ticket.intent,
        "hotel_timezone": new_ticket.hotel_timezone or "UTC",
        "linked_tickets_count": len(prior_tickets)
    }

    if idempotency_key:
        record_id = f"{current_user.id}:{idempotency_key}"
        idem_entry = IdempotencyRecord(
            id=record_id,
            user_id=current_user.id,
            key=idempotency_key,
            ticket_id=new_ticket.id,
            response_json=json.dumps(response_data),
            request_hash=current_payload_hash
        )
        db.add(idem_entry)

    db.commit()

    return response_data


@app.get("/api/tickets/{ticket_id}")
def get_ticket_details(
    ticket_id: str,
    response: Response = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves full ticket detail.
    - If requester belongs to another agency -> 404 Not Found (tenant isolation).
    - If requester belongs to same agency -> InternalNotes and side_conversations are withheld.
    - Staff members receive complete operations view.
    - Sets ETag header for optimistic concurrency control.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Access control
    if current_user.role == "Requester" and ticket.agency_id != current_user.agency_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if response is not None:
        response.headers["ETag"] = f'W/"{ticket.version}"'

    # Format messages
    messages = []
    for msg in ticket.messages:
        if current_user.role == "Requester" and msg.message_type == "InternalNote":
            continue  # Requesters NEVER see internal staff notes
        messages.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "message_type": msg.message_type,
            "content": msg.content,
            "created_at": msg.created_at.isoformat()
        })

    # Format side conversations
    side_threads = []
    if current_user.role != "Requester":
        for sc in ticket.side_conversations:
            side_threads.append({
                "id": sc.id,
                "supplier_name": sc.supplier_name,
                "subject": sc.subject,
                "recipients": [r.email for r in sc.recipients],
                "messages": [{
                    "id": m.id,
                    "sender_email": m.sender_email,
                    "body": m.body,
                    "created_at": m.created_at.isoformat()
                } for m in sc.messages]
            })

    # Linked tickets (filtered to requester's agency for Requesters)
    linked_tickets = []
    links = db.query(TicketLink).filter(
        (TicketLink.ticket_id == ticket_id) | (TicketLink.linked_ticket_id == ticket_id)
    ).all()
    for l in links:
        other_id = l.linked_ticket_id if l.ticket_id == ticket_id else l.ticket_id
        if current_user.role == "Requester":
            other_ticket = db.query(Ticket.agency_id).filter(Ticket.id == other_id).first()
            if other_ticket and other_ticket.agency_id == current_user.agency_id:
                linked_tickets.append(other_id)
        else:
            linked_tickets.append(other_id)

    now = datetime.now(timezone.utc)
    sla = evaluate_travel_sla(
        status=ticket.status,
        check_in_date=ticket.check_in_date,
        lcd_date=ticket.lcd_date,
        priority=ticket.priority,
        intent=ticket.intent,
        now=now
    )
    agency_tier = ticket.agency.tier if ticket.agency else None
    if not agency_tier:
        agency = db.query(Agency).filter(Agency.id == ticket.agency_id).first()
        if agency:
            agency_tier = agency.tier

    queue_score = compute_ticket_queue_score(
        ticket=ticket,
        agency_tier=agency_tier,
        now=now,
        user_role=current_user.role
    )

    return {
        "id": ticket.id,
        "tboh_id": ticket.tboh_id,
        "agency_id": ticket.agency_id,
        "title": ticket.title,
        "description": ticket.description,
        "intent": ticket.intent,
        "priority": ticket.priority,
        "status": ticket.status,
        "hotel_timezone": ticket.hotel_timezone or "UTC",
        "check_in_date": ticket.check_in_date.isoformat(),
        "lcd_date": ticket.lcd_date.isoformat() if ticket.lcd_date else None,
        "assigned_to": ticket.assigned_to if current_user.role != "Requester" else None,
        "routing_reason": ticket.routing_reason if current_user.role != "Requester" else None,
        "sla": sla,
        "queue_score": queue_score if current_user.role != "Requester" else None,
        "suggested_bug_link": ticket.suggested_bug_link,
        "linked_ticket_ids": linked_tickets,
        "messages": messages,
        "side_conversations": side_threads,
        "version": ticket.version,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat()
    }


@app.get("/api/tickets/{ticket_id}/audit-trail")
def get_ticket_audit_trail(
    ticket_id: str,
    limit: int = Query(50, ge=1, le=500),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns immutable audit trail history for a ticket.
    Enforces multi-tenant isolation:
    - Requesters can only access audit trails for tickets belonging to their agency (cross-agency -> 404).
    - Internal staff operational actions and details are sanitized for requesters.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role == "Requester" and ticket.agency_id != current_user.agency_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    query = db.query(AuditLog).filter(AuditLog.ticket_id == ticket_id)
    if order == "asc":
        query = query.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    else:
        query = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

    records = query.limit(limit).all()
    results = []
    for r in records:
        try:
            details_obj = json.loads(r.details) if r.details else {}
        except Exception:
            details_obj = {"raw": r.details}

        if current_user.role == "Requester":
            if r.action in ("internal_note_added", "bypass_escalated", "transfer"):
                continue
            if isinstance(details_obj, dict):
                details_obj.pop("routing_reason", None)
                details_obj.pop("internal", None)

        results.append({
            "id": r.id,
            "ticket_id": r.ticket_id,
            "actor_id": r.actor_id,
            "action": r.action,
            "details": details_obj,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })

    return results


# ============================================================================
# 3. TICKET ACTIONS (ASSIGN, STATUS, ESCALATE, TRANSFER)
# ============================================================================

@app.post("/api/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: str,
    payload: TicketAssignSchema,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assigns an operations ticket to a designated staff member atomically with race protection."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot assign tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    target_agent = db.query(User).filter(User.id == payload.agent_id).first()
    if not target_agent or target_agent.role not in ["Agent", "Lead", "EscalationManager"]:
        raise HTTPException(status_code=400, detail="Target agent must be internal staff")

    req_version = payload.version
    if req_version is None and if_match is not None:
        try:
            req_version = int(if_match.strip().lstrip("W/").strip('"'))
        except ValueError:
            pass

    if req_version is not None and ticket.version != req_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {req_version}."
        )

    old_agent = ticket.assigned_to
    current_version = ticket.version

    filter_conditions = [
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ]
    if old_agent is None:
        filter_conditions.append(Ticket.assigned_to.is_(None))
    else:
        filter_conditions.append(Ticket.assigned_to == old_agent)

    new_status = "Open" if ticket.status == "New" else ticket.status
    now = datetime.now(timezone.utc)
    ticket.status = new_status
    ticket.assigned_to = payload.agent_id
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)
    rowcount = db.query(Ticket).filter(*filter_conditions).update(
        {
            Ticket.assigned_to: payload.agent_id,
            Ticket.status: new_status,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.priority_weight: ticket.priority_weight,
            Ticket.queue_score: ticket.queue_score,
            Ticket.score_computed_at: ticket.score_computed_at,
            Ticket.version: current_version + 1,
            Ticket.updated_at: now
        },
        synchronize_session=False
    )
    if rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Ticket assignment race lost; ticket was claimed or modified by another agent."
        )

    emit_outbox_event(
        db=db,
        event_type="ticket.assigned",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload={"ticket_id": ticket.id, "assigned_to": payload.agent_id, "previous_agent": old_agent}
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.assigned",
        details={"assigned_to": payload.agent_id, "previous_agent": old_agent}
    )
    db.commit()

    return {"status": "success", "ticket_id": ticket.id, "assigned_to": payload.agent_id, "version": current_version + 1}


@app.post("/api/tickets/{ticket_id}/unassign")
def unassign_ticket(
    ticket_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unassigns ticket returning it to triage atomically."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot unassign tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if if_match is not None:
        try:
            req_version = int(if_match.strip().lstrip("W/").strip('"'))
            if ticket.version != req_version:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {req_version}."
                )
        except ValueError:
            pass

    old_agent = ticket.assigned_to
    current_version = ticket.version

    new_status = "Open" if ticket.status in ["New", "Open"] else ticket.status
    now = datetime.now(timezone.utc)
    ticket.status = new_status
    ticket.assigned_to = None
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

    rowcount = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ).update(
        {
            Ticket.assigned_to: None,
            Ticket.status: new_status,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.priority_weight: ticket.priority_weight,
            Ticket.queue_score: ticket.queue_score,
            Ticket.score_computed_at: ticket.score_computed_at,
            Ticket.version: current_version + 1,
            Ticket.updated_at: now
        },
        synchronize_session=False
    )
    if rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Concurrent modification detected during unassignment."
        )

    emit_outbox_event(
        db=db,
        event_type="ticket.unassigned",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload={"ticket_id": ticket.id, "previous_agent": old_agent}
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.unassigned",
        details={"previous_agent": old_agent}
    )
    db.commit()

    return {"status": "success", "ticket_id": ticket.id, "assigned_to": None, "version": current_version + 1}


@app.post("/api/tickets/{ticket_id}/status")
def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdateSchema,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transitions ticket status according to ALLOWED_STATUS_TRANSITIONS graph.
    Status transitions are restricted strictly to internal operations staff (Requesters get 403).
    Returns 409 Conflict if transition is not permitted or if stale version detected.
    """
    if current_user.role == "Requester":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only internal operations staff can update ticket status"
        )

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    req_version = payload.version
    if req_version is None and if_match is not None:
        try:
            req_version = int(if_match.strip().lstrip("W/").strip('"'))
        except ValueError:
            pass

    if req_version is not None and ticket.version != req_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {req_version}."
        )

    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
    if payload.status != ticket.status and payload.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid status transition from '{ticket.status}' to '{payload.status}'. Allowed: {allowed}"
        )

    old_status = ticket.status
    old_priority = ticket.priority
    current_version = ticket.version
    now = datetime.now(timezone.utc)
    ticket.status = payload.status
    if payload.priority is not None:
        ticket.priority = payload.priority
        ticket.priority_weight = PRIORITY_SCORES.get(payload.priority, 200.0)
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

    rowcount = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ).update(
        {
            Ticket.status: payload.status,
            Ticket.priority: ticket.priority,
            Ticket.priority_weight: ticket.priority_weight,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.queue_score: ticket.queue_score,
            Ticket.score_computed_at: ticket.score_computed_at,
            Ticket.version: current_version + 1,
            Ticket.updated_at: now
        },
        synchronize_session=False
    )
    if rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Concurrent modification detected during status update."
        )

    emit_outbox_event(
        db=db,
        event_type="ticket.status_changed",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload={
            "ticket_id": ticket.id,
            "old_status": old_status,
            "new_status": payload.status,
            "old_priority": old_priority,
            "new_priority": ticket.priority
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.status_changed",
        details={
            "old_status": old_status,
            "new_status": payload.status,
            "old_priority": old_priority,
            "new_priority": ticket.priority
        }
    )
    db.commit()

    return {"status": "success", "ticket_id": ticket.id, "old_status": old_status, "new_status": payload.status, "version": current_version + 1}


@app.post("/api/tickets/{ticket_id}/escalate")
def escalate_ticket(
    ticket_id: str,
    payload: TicketEscalateSchema,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Escalates an operations ticket:
    - Sets status to 'Escalated'
    - Reassigns ticket to configured Escalation Manager (DEFAULT_ESCALATION_MANAGER_ID)
    - Records reason in audit log.
    - Protected with optimistic version checking.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot escalate tickets directly")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    req_version = payload.version
    if req_version is None and if_match is not None:
        try:
            req_version = int(if_match.strip().lstrip("W/").strip('"'))
        except ValueError:
            pass

    if req_version is not None and ticket.version != req_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {req_version}."
        )

    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
    if "Escalated" not in allowed and ticket.status != "Escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot escalate ticket from current status '{ticket.status}'"
        )

    old_status = ticket.status
    old_assignee = ticket.assigned_to
    current_version = ticket.version
    routing_reason = f"Escalated to Escalation Manager ({DEFAULT_ESCALATION_MANAGER_ID})"

    now = datetime.now(timezone.utc)
    ticket.status = "Escalated"
    ticket.priority = payload.priority or "Urgent"
    ticket.priority_weight = PRIORITY_SCORES.get(ticket.priority, PRIORITY_SCORES["Urgent"])
    ticket.assigned_to = DEFAULT_ESCALATION_MANAGER_ID
    ticket.routing_reason = routing_reason
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

    rowcount = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ).update(
        {
            Ticket.status: "Escalated",
            Ticket.priority: ticket.priority,
            Ticket.priority_weight: ticket.priority_weight,
            Ticket.assigned_to: DEFAULT_ESCALATION_MANAGER_ID,
            Ticket.routing_reason: routing_reason,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.queue_score: ticket.queue_score,
            Ticket.score_computed_at: ticket.score_computed_at,
            Ticket.version: current_version + 1,
            Ticket.updated_at: now
        },
        synchronize_session=False
    )
    if rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Concurrent modification detected during escalation."
        )

    # Public event payload omits free-text reason to protect internal operational discussions
    emit_outbox_event(
        db=db,
        event_type="ticket.escalated",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload={
            "ticket_id": ticket.id,
            "assigned_to": DEFAULT_ESCALATION_MANAGER_ID,
            "old_status": old_status
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.escalated",
        details={"reason": payload.reason, "assigned_to": DEFAULT_ESCALATION_MANAGER_ID, "old_assignee": old_assignee}
    )
    db.commit()

    return {
        "status": "success",
        "ticket_id": ticket.id,
        "new_status": "Escalated",
        "assigned_to": DEFAULT_ESCALATION_MANAGER_ID,
        "routing_reason": routing_reason,
        "version": current_version + 1
    }


@app.post("/api/tickets/{ticket_id}/transfer")
def transfer_ticket(
    ticket_id: str,
    payload: TicketTransferSchema,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transfers ticket to a new agent while strictly preserving all side conversation recipients.
    MVP-4 Core Rule: Side thread recipients do NOT get wiped or overwritten on ticket hand-off.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot transfer tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if payload.target_agent_id == ticket.assigned_to:
        raise HTTPException(status_code=400, detail=f"Ticket is already assigned to {ticket.assigned_to}")

    target_agent = db.query(User).filter(User.id == payload.target_agent_id).first()
    if not target_agent or target_agent.role not in ["Agent", "Lead", "EscalationManager"]:
        raise HTTPException(status_code=400, detail="Target agent must be internal staff")

    req_version = payload.version
    if req_version is None and if_match is not None:
        try:
            req_version = int(if_match.strip().lstrip("W/").strip('"'))
        except ValueError:
            pass

    if req_version is not None and ticket.version != req_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {req_version}."
        )

    old_agent = ticket.assigned_to
    current_version = ticket.version

    routing_reason = f"Transferred from {old_agent} to {payload.target_agent_id}"
    now = datetime.now(timezone.utc)
    ticket.assigned_to = payload.target_agent_id
    ticket.routing_reason = routing_reason
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

    rowcount = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ).update(
        {
            Ticket.assigned_to: payload.target_agent_id,
            Ticket.routing_reason: routing_reason,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.priority_weight: ticket.priority_weight,
            Ticket.queue_score: ticket.queue_score,
            Ticket.score_computed_at: ticket.score_computed_at,
            Ticket.version: current_version + 1,
            Ticket.updated_at: now
        },
        synchronize_session=False
    )
    if rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Concurrent modification detected during transfer."
        )

    # Verify side conversations are preserved
    side_convo_count = len(ticket.side_conversations)
    recipients_count = sum(len(sc.recipients) for sc in ticket.side_conversations)

    emit_outbox_event(
        db=db,
        event_type="ticket.transferred",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="internal",
        payload={
            "ticket_id": ticket.id,
            "old_agent": old_agent,
            "new_agent": payload.target_agent_id,
            "reason": payload.reason
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.transferred",
        details={"old_agent": old_agent, "new_agent": payload.target_agent_id, "reason": payload.reason}
    )
    db.commit()

    return {
        "status": "success",
        "ticket_id": ticket.id,
        "assigned_to": payload.target_agent_id,
        "routing_reason": routing_reason,
        "side_conversations_preserved": side_convo_count,
        "total_recipients_preserved": recipients_count,
        "version": current_version + 1
    }


# ============================================================================
# 3.1 BULK TICKET OPERATIONS
# ============================================================================

@app.post("/api/tickets/bulk-assign")
def bulk_assign_tickets(
    payload: BulkAssignRequestSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Atomically bulk-assigns multiple operations tickets to a designated internal staff agent.
    Restricted to internal staff (Lead, EscalationManager, Agent). Requesters receive 403.
    Emits outbox events and audit logs for each modified ticket.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot bulk-assign tickets")

    target_agent = db.query(User).filter(User.id == payload.agent_id).first()
    if not target_agent or target_agent.role not in ["Agent", "Lead", "EscalationManager"]:
        raise HTTPException(status_code=400, detail="Target agent must be internal staff")

    tickets = db.query(Ticket).filter(Ticket.id.in_(payload.ticket_ids)).all()
    if not tickets:
        raise HTTPException(status_code=404, detail="No matching tickets found for bulk assignment")

    now = datetime.now(timezone.utc)
    assigned_ids = []

    for ticket in tickets:
        old_agent = ticket.assigned_to
        new_status = "Open" if ticket.status == "New" else ticket.status
        ticket.assigned_to = payload.agent_id
        ticket.status = new_status
        ticket.version = (ticket.version or 1) + 1
        ticket.updated_at = now

        agency_tier = ticket.agency.tier if ticket.agency else None
        compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

        emit_outbox_event(
            db=db,
            event_type="ticket.assigned",
            ticket_id=ticket.id,
            agency_id=ticket.agency_id,
            visibility="public",
            payload={"ticket_id": ticket.id, "assigned_to": payload.agent_id, "bulk": True}
        )
        record_audit_log(
            db=db,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            action="ticket.bulk_assigned",
            details={"assigned_to": payload.agent_id, "previous_agent": old_agent}
        )
        assigned_ids.append(ticket.id)

    db.commit()

    return {
        "status": "success",
        "total_requested": len(payload.ticket_ids),
        "total_assigned": len(assigned_ids),
        "agent_id": payload.agent_id,
        "assigned_ticket_ids": assigned_ids
    }


@app.post("/api/tickets/bulk-status")
def bulk_update_status(
    payload: BulkStatusUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bulk updates status across multiple tickets.
    Enforces ALLOWED_STATUS_TRANSITIONS per ticket.
    Reports succeeded count and detailed reasons for skipped/invalid transitions.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot update ticket status")

    tickets = db.query(Ticket).filter(Ticket.id.in_(payload.ticket_ids)).all()
    if not tickets:
        raise HTTPException(status_code=404, detail="No matching tickets found")

    now = datetime.now(timezone.utc)
    succeeded = []
    failed = []

    for ticket in tickets:
        allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
        if payload.status != ticket.status and payload.status not in allowed:
            failed.append({
                "ticket_id": ticket.id,
                "current_status": ticket.status,
                "reason": f"Invalid transition from '{ticket.status}' to '{payload.status}'"
            })
            continue

        old_status = ticket.status
        ticket.status = payload.status
        ticket.version = (ticket.version or 1) + 1
        ticket.updated_at = now

        agency_tier = ticket.agency.tier if ticket.agency else None
        compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

        emit_outbox_event(
            db=db,
            event_type="ticket.status_changed",
            ticket_id=ticket.id,
            agency_id=ticket.agency_id,
            visibility="public",
            payload={"ticket_id": ticket.id, "old_status": old_status, "new_status": payload.status, "bulk": True}
        )
        record_audit_log(
            db=db,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            action="ticket.bulk_status_changed",
            details={"old_status": old_status, "new_status": payload.status}
        )
        succeeded.append(ticket.id)

    db.commit()

    return {
        "status": "partial_success" if failed else "success",
        "total_requested": len(payload.ticket_ids),
        "total_succeeded": len(succeeded),
        "total_failed": len(failed),
        "target_status": payload.status,
        "succeeded_ticket_ids": succeeded,
        "failed_details": failed
    }


# ============================================================================
# 4. MESSAGES & NOTES ENDPOINTS
# ============================================================================

@app.post("/api/tickets/{ticket_id}/messages", status_code=status.HTTP_201_CREATED)
def post_ticket_message(
    ticket_id: str,
    payload: MessageCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Appends a message or note to a ticket.
    - Requesters can only post PublicReply. Posting InternalNote yields 403 Forbidden.
    - InternalNotes emit events with visibility='internal'.
    - PublicReplies emit events with visibility='public'.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role == "Requester":
        if ticket.agency_id != current_user.agency_id:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if payload.message_type == "InternalNote":
            raise HTTPException(status_code=403, detail="Forbidden: Agency requesters cannot post internal notes")

    if payload.message_type not in ["PublicReply", "InternalNote"]:
        raise HTTPException(status_code=400, detail="Invalid message_type; must be PublicReply or InternalNote")

    msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    msg = TicketMessage(
        id=msg_id,
        ticket_id=ticket.id,
        sender_id=current_user.id,
        message_type=payload.message_type,
        content=payload.content,
        created_at=now
    )
    db.add(msg)

    # Scoped visibility: InternalNotes are strictly internal
    visibility = "internal" if payload.message_type == "InternalNote" else "public"

    emit_outbox_event(
        db=db,
        event_type="message.created",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility=visibility,
        payload={
            "message_id": msg_id,
            "ticket_id": ticket.id,
            "sender_id": current_user.id,
            "message_type": payload.message_type
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="message.created",
        details={"message_type": payload.message_type, "visibility": visibility}
    )
    db.commit()

    return {
        "id": msg.id,
        "ticket_id": msg.ticket_id,
        "message_type": msg.message_type,
        "visibility": visibility,
        "created_at": msg.created_at.isoformat()
    }


# ============================================================================
# 5. SIDE CONVERSATION THREADS (SUPPLIER LIAISON)
# ============================================================================

@app.get("/api/tickets/{ticket_id}/side-threads")
def list_side_threads(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all supplier side conversations. Restricted strictly to internal staff."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Agency requesters cannot view supplier side threads")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    threads = []
    for sc in ticket.side_conversations:
        threads.append({
            "id": sc.id,
            "supplier_name": sc.supplier_name,
            "subject": sc.subject,
            "recipients": [r.email for r in sc.recipients],
            "messages_count": len(sc.messages),
            "created_at": sc.created_at.isoformat()
        })
    return {"ticket_id": ticket.id, "side_threads": threads}


@app.post("/api/tickets/{ticket_id}/side-threads", status_code=status.HTTP_201_CREATED)
def create_side_thread(
    ticket_id: str,
    payload: SideThreadCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Creates an external side conversation thread with hotel/airline suppliers.
    Restricted strictly to internal staff (Requesters get 403).
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Agency requesters cannot create supplier side threads")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    sc_id = f"SC-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    side_convo = SideConversation(
        id=sc_id,
        ticket_id=ticket.id,
        supplier_name=payload.supplier_name,
        subject=payload.subject,
        created_by=current_user.id,
        created_at=now
    )
    db.add(side_convo)
    db.flush()

    for idx, email in enumerate(payload.recipients):
        db.add(SideConversationRecipient(
            id=f"SCR-{uuid.uuid4().hex[:8].upper()}",
            side_conversation_id=sc_id,
            email=email
        ))

    initial_msg = SideConversationMessage(
        id=f"SCM-{uuid.uuid4().hex[:8].upper()}",
        side_conversation_id=sc_id,
        sender_email=current_user.email,
        body=payload.initial_message,
        created_at=now
    )
    db.add(initial_msg)

    emit_outbox_event(
        db=db,
        event_type="side_conversation.created",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="internal",
        payload={
            "side_conversation_id": sc_id,
            "supplier_name": payload.supplier_name,
            "recipients": payload.recipients
        }
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="side_conversation.created",
        details={"supplier": payload.supplier_name, "recipients": payload.recipients}
    )
    db.commit()

    return {
        "id": sc_id,
        "ticket_id": ticket.id,
        "supplier_name": payload.supplier_name,
        "recipients": payload.recipients,
        "created_at": now.isoformat()
    }


@app.post("/api/tickets/{ticket_id}/side-threads/{side_thread_id}/messages", status_code=status.HTTP_201_CREATED)
def post_side_thread_message(
    ticket_id: str,
    side_thread_id: str,
    payload: SideThreadMessageCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Appends an email/message to a supplier side conversation."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Agency requesters cannot participate in supplier side threads")

    sc = db.query(SideConversation).filter(
        SideConversation.id == side_thread_id,
        SideConversation.ticket_id == ticket_id
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Side conversation thread not found")

    msg_id = f"SCM-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    msg = SideConversationMessage(
        id=msg_id,
        side_conversation_id=sc.id,
        sender_email=current_user.email,
        body=payload.body,
        created_at=now
    )
    db.add(msg)

    emit_outbox_event(
        db=db,
        event_type="side_conversation.message_created",
        ticket_id=ticket_id,
        agency_id=sc.ticket.agency_id,
        visibility="internal",
        payload={"side_conversation_id": sc.id, "message_id": msg_id}
    )
    record_audit_log(
        db=db,
        ticket_id=ticket_id,
        actor_id=current_user.id,
        action="side_conversation.message_created",
        details={"side_thread_id": sc.id}
    )
    db.commit()

    return {
        "id": msg_id,
        "side_conversation_id": sc.id,
        "sender_email": msg.sender_email,
        "created_at": msg.created_at.isoformat()
    }


# ============================================================================
# 11. SUGGESTED BUG LINK (MVP-5)
# ============================================================================

@app.post("/api/tickets/{ticket_id}/link-suggestion")
def link_suggested_bug(
    ticket_id: str,
    payload: TicketLinkSuggestionSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Staff-only action: Suggests / links a product defect or JIRA/system issue link (MVP-5).
    Requesters receive 403 Forbidden.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot link system bug suggestions")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.suggested_bug_link = payload.bug_link
    ticket.updated_at = datetime.now(timezone.utc)

    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.suggested_bug_linked",
        details={"suggested_bug_link": payload.bug_link}
    )
    db.commit()

    return {
        "id": ticket.id,
        "suggested_bug_link": ticket.suggested_bug_link,
        "message": "Bug link successfully suggested"
    }


# ============================================================================
# 12. INSIGHTS / THEMES (MVP-5)
# ============================================================================

@app.get("/api/insights/themes")
def get_top_themes(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Insights view: Top themes this week + sample tickets (MVP-5).
    Accessible strictly to Lead and EscalationManager roles.
    Computes percentages dynamically from seed data; works on SQLite and PostgreSQL.
    """
    if current_user.role not in ["Lead", "EscalationManager"]:
        raise HTTPException(status_code=403, detail="Forbidden: Insights view requires Lead or EscalationManager role")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Query counts grouped by theme for tickets created within time window
    theme_counts = db.query(
        TicketTheme.theme,
        func.count(TicketTheme.id).label("count")
    ).join(Ticket, TicketTheme.ticket_id == Ticket.id)\
     .filter(Ticket.created_at >= cutoff)\
     .group_by(TicketTheme.theme)\
     .order_by(func.count(TicketTheme.id).desc())\
     .all()

    total_tagged = sum(c for _, c in theme_counts)

    results = []
    for theme_name, count in theme_counts:
        pct = round((count * 100.0 / total_tagged), 1) if total_tagged > 0 else 0.0

        # Sample up to 3 ticket IDs for this theme within the window
        samples = db.query(TicketTheme.ticket_id)\
                    .join(Ticket, TicketTheme.ticket_id == Ticket.id)\
                    .filter(TicketTheme.theme == theme_name, Ticket.created_at >= cutoff)\
                    .order_by(Ticket.created_at.desc())\
                    .limit(3)\
                    .all()

        results.append({
            "theme": theme_name,
            "count": count,
            "percentage": pct,
            "sample_ticket_ids": [s[0] for s in samples]
        })

    return {
        "time_window_days": days,
        "total_tagged_records": total_tagged,
        "themes": results
    }


# ============================================================================
# 12. AGENCY MANAGEMENT & TIER UPDATES
# ============================================================================

@app.patch("/api/agencies/{agency_id}/tier")
@app.put("/api/agencies/{agency_id}/tier")
def update_agency_tier_endpoint(
    agency_id: str,
    payload: AgencyTierUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates an agency's tier (standard, gold, platinum) and immediately recomputes
    queue_score for all active tickets belonging to that agency.
    """
    if current_user.role not in ["Lead", "EscalationManager"]:
        raise HTTPException(status_code=403, detail="Forbidden: Only Lead or EscalationManager can update agency tier")

    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    normalized_tier = payload.tier.lower().strip()
    if normalized_tier not in ["platinum", "gold", "standard"]:
        raise HTTPException(status_code=400, detail="Invalid agency tier. Allowed: standard, gold, platinum")

    agency.tier = normalized_tier
    now = datetime.now(timezone.utc)

    # Recompute stored urgency fields for all active tickets belonging to this agency
    active_tickets = db.query(Ticket).filter(
        Ticket.agency_id == agency_id,
        Ticket.status.in_(["New", "Open", "Pending", "Escalated"])
    ).all()
    for t in active_tickets:
        compute_ticket_urgency_fields(t, agency_tier=normalized_tier, now=now)

    db.commit()
    return {
        "status": "success",
        "agency_id": agency_id,
        "tier": normalized_tier,
        "tickets_updated": len(active_tickets)
    }


# ============================================================================
# 13. UNCAPPED OPS DATA EXPORT (MVP-6)
# ============================================================================

def sanitize_csv_cell(val: Any) -> str:
    """
    Prevents CSV formula injection / CSV spreadsheet execution vulnerabilities.
    If a cell value begins with '=', '+', '-', '@', '\t', or '\r', prefixes with a single quote.
    """
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


CSV_EXPORT_MAX_CONCURRENCY = int(os.environ.get("CSV_EXPORT_MAX_CONCURRENCY", "2"))
CSV_EXPORT_MAX_DURATION_SECONDS = float(os.environ.get("CSV_EXPORT_MAX_DURATION_SECONDS", "30.0"))
_export_semaphore = threading.BoundedSemaphore(CSV_EXPORT_MAX_CONCURRENCY)


def get_csv_export_default_limit() -> int:
    """
    Safely parses CSV_EXPORT_DEFAULT_LIMIT environment variable.
    Falls back to 50000 with a logged warning if value is missing, non-positive, or malformed.
    """
    val = os.environ.get("CSV_EXPORT_DEFAULT_LIMIT", "50000")
    try:
        limit = int(str(val).replace(",", "").strip())
        if limit <= 0:
            logger.warning(f"Invalid non-positive CSV_EXPORT_DEFAULT_LIMIT='{val}'. Falling back to 50000.")
            return 50000
        return limit
    except (ValueError, TypeError) as exc:
        logger.warning(f"Failed to parse CSV_EXPORT_DEFAULT_LIMIT='{val}': {exc}. Falling back to 50000.")
        return 50000


@app.get("/api/export/tickets.csv")
def export_tickets_csv(
    status: Optional[str] = None,
    agency_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    cursor: Optional[str] = Query(None, description="Cursor for pagination: ID of the last seen ticket"),
    limit: Optional[int] = Query(None, description="Max rows per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    CSV data streaming export for ops beyond 3K-row UX barrier (MVP-6).
    Restricted strictly to Lead role. Memory-safe streaming via generator yield_per.
    Applies formula injection sanitization to protect operations spreadsheets.
    Protected by concurrency limiter (max CSV_EXPORT_MAX_CONCURRENCY, default 2).
    """
    if current_user.role != "Lead":
        raise HTTPException(status_code=403, detail="Forbidden: Export is restricted to Lead role")

    acquired = _export_semaphore.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="Export service busy: maximum concurrent exports reached. Please retry shortly.",
            headers={"Retry-After": "10"}
        )

    released = False
    def release_semaphore():
        nonlocal released
        if not released:
            released = True
            try:
                _export_semaphore.release()
            except ValueError:
                pass

    try:
        # Select only exported columns instead of querying full ORM models
        query = db.query(
            Ticket.id,
            Ticket.tboh_id,
            Ticket.agency_id,
            Ticket.title,
            Ticket.intent,
            Ticket.priority,
            Ticket.status,
            Ticket.check_in_date,
            Ticket.lcd_date,
            Ticket.assigned_to,
            Ticket.created_at
        )
        if status:
            query = query.filter(Ticket.status == status)
        if agency_id:
            query = query.filter(Ticket.agency_id == agency_id)
        if from_date:
            query = query.filter(Ticket.created_at >= from_date)
        if to_date:
            query = query.filter(Ticket.created_at <= to_date)

        if cursor:
            cursor_ticket = db.query(Ticket.created_at, Ticket.id).filter(Ticket.id == cursor).first()
            if not cursor_ticket:
                raise HTTPException(status_code=404, detail=f"Cursor ticket '{cursor}' not found")
            query = query.filter(
                or_(
                    Ticket.created_at < cursor_ticket.created_at,
                    (Ticket.created_at == cursor_ticket.created_at) & (Ticket.id < cursor_ticket.id)
                )
            )

        query = query.order_by(Ticket.created_at.desc(), Ticket.id.desc())

        default_limit = get_csv_export_default_limit()
        effective_limit = limit if (limit is not None and limit > 0) else default_limit

        # Keyset next-cursor probe: fetch limit+1 rows via keyset without OFFSET
        cursor_probe = query.with_entities(Ticket.id).limit(effective_limit + 1).all()
        if len(cursor_probe) > effective_limit:
            has_more = True
            next_cursor = cursor_probe[effective_limit - 1][0]
        else:
            has_more = False
            next_cursor = None
    except Exception:
        release_semaphore()
        raise

    def iter_csv():
        try:
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow([
                "id", "tboh_id", "agency_id", "title", "intent", "priority",
                "status", "check_in_date", "lcd_date", "assigned_to", "created_at"
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

            # Stream strictly via yield_per(500) with scalar tuples to keep memory footprint constant
            stream_delay = float(os.environ.get("CSV_EXPORT_STREAM_DELAY", "0"))
            for row in query.limit(effective_limit).yield_per(500):
                if stream_delay > 0:
                    time.sleep(stream_delay)
                writer.writerow([
                    sanitize_csv_cell(row.id),
                    sanitize_csv_cell(row.tboh_id),
                    sanitize_csv_cell(row.agency_id),
                    sanitize_csv_cell(row.title),
                    sanitize_csv_cell(row.intent or ""),
                    sanitize_csv_cell(row.priority),
                    sanitize_csv_cell(row.status),
                    sanitize_csv_cell(row.check_in_date.isoformat() if row.check_in_date else ""),
                    sanitize_csv_cell(row.lcd_date.isoformat() if row.lcd_date else ""),
                    sanitize_csv_cell(row.assigned_to or ""),
                    sanitize_csv_cell(row.created_at.isoformat() if row.created_at else "")
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

        finally:
            release_semaphore()

    headers = {
        "Content-Disposition": "attachment; filename=opsdesk_tickets_export.csv",
        "Content-Type": "text/csv; charset=utf-8"
    }
    if has_more and next_cursor:
        headers["X-Next-Cursor"] = next_cursor

    return StreamingResponse(
        iter_csv(),
        headers=headers,
        media_type="text/csv",
        background=BackgroundTask(release_semaphore)
    )

