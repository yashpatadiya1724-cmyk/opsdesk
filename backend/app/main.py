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
    LoginRequest, LoginResponse
)
from backend.app.auth import get_current_user, verify_password, create_access_token
from backend.app.events import emit_outbox_event, record_audit_log
from backend.config.routing_config import (
    DEFAULT_ESCALATION_MANAGER_ID,
    REGION_MAPPING,
    EMERGENCY_BYPASS_HOURS
)
from backend.services.sla_engine import evaluate_travel_sla, effective_deadline_hours
from backend.services.routing_engine import (
    CandidateAgent, select_agent_tier1, calculate_queue_score_tier2, compute_ticket_urgency_fields
)
from backend.services.intent_classifier import suggest_ticket_intent

import os
import time
import logging
import threading
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("opsdesk.access")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="OpsDesk: B2B Travel Operations Case Management API",
    description="Operational case management platform tailored for high-volume B2B travel operations.",
    version="1.0.0"
)

cors_origins_env = os.environ.get("ALLOWED_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
RATE_LIMIT_MAX_KEYS = int(os.environ.get("RATE_LIMIT_MAX_KEYS", "10000"))
RATE_LIMIT_WINDOW = 60.0  # seconds

IDEMPOTENCY_TTL_HOURS = int(os.environ.get("IDEMPOTENCY_TTL_HOURS", "24"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
ALLOW_DEMO_AUTH = os.environ.get("ALLOW_DEMO_AUTH", "false").lower() in ("true", "1", "yes")

_rate_limit_lock = threading.Lock()
_rate_limit_records: Dict[str, List[float]] = {}


def validate_production_auth_settings():
    """
    Refuses startup when running in production environment with demo authentication,
    unless explicitly overridden via ALLOW_DEMO_AUTH=true.
    """
    env = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).lower()
    auth_mode = os.environ.get("AUTH_MODE", "demo").lower()
    allow_demo = os.environ.get("ALLOW_DEMO_AUTH", "false").lower() in ("true", "1", "yes")
    if env == "production" and auth_mode == "demo" and not allow_demo:
        msg = "Production environment requires AUTH_MODE=jwt unless ALLOW_DEMO_AUTH=true (Refusing to start in APP_ENV=production with unauthenticated demo headers)."
        logger.error(msg)
        raise RuntimeError(msg)
    elif env == "production" and allow_demo:
        logger.warning("WARNING: APP_ENV=production is running with demo authentication because ALLOW_DEMO_AUTH=true is set. Ensure this is intentional!")


def purge_expired_idempotency_records(db: Session) -> int:
    """
    Assumption: Purges in-database idempotency records older than IDEMPOTENCY_TTL_HOURS (default 24).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    deleted = db.query(IdempotencyRecord).filter(IdempotencyRecord.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted


@app.on_event("startup")
def on_app_startup():
    validate_production_auth_settings()
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from backend.app.database import SessionLocal, engine, ensure_schema_migrations
            ensure_schema_migrations(engine)
            with SessionLocal() as db:
                purged = purge_expired_idempotency_records(db)
                if purged > 0:
                    logger.info(f'{{"event": "idempotency_startup_purge", "purged": {purged}}}')
        except Exception as exc:
            logger.warning(f"Startup maintenance warning: {exc}")

@app.middleware("http")
async def opsdesk_protection_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start_time = time.time()

    # Rate limiting check: Keyed on both X-User-Id and client IP
    # NOTE: Behind a reverse proxy (e.g. Nginx, Cloudflare), request.client.host represents the proxy IP
    # unless trusted proxy forwarding (e.g. X-Forwarded-For with CIDR verification) is configured.
    # Status: planned trusted proxy config, not built.
    if request.url.path not in ["/health", "/ready", "/docs", "/openapi.json"]:
        user_id = request.headers.get("X-User-Id")
        client_ip = request.client.host if request.client else "unknown"

        keys_to_check = []
        if user_id:
            keys_to_check.append(f"user:{user_id}")
        if client_ip:
            keys_to_check.append(f"ip:{client_ip}")

        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW

        with _rate_limit_lock:
            # 1. Check if any key violates limit
            for key in keys_to_check:
                existing = _rate_limit_records.get(key, [])
                active = [t for t in existing if t > window_start]
                if len(active) >= RATE_LIMIT_PER_MINUTE:
                    _rate_limit_records[key] = active
                    logger.warning(f'{{"event": "rate_limited", "key": "{key}", "request_id": "{request_id}", "path": "{request.url.path}"}}')
                    resp = Response(
                        content=json.dumps({"detail": "Rate limit exceeded. Please retry later."}),
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        media_type="application/json",
                        headers={"Retry-After": "60", "X-Request-ID": request_id}
                    )
                    return resp

            # 2. Bounded dict eviction: remove stale keys if size exceeds max bound
            if len(_rate_limit_records) >= RATE_LIMIT_MAX_KEYS:
                stale_keys = [k for k, v in _rate_limit_records.items() if not v or v[-1] <= window_start]
                for k in stale_keys:
                    del _rate_limit_records[k]
                if len(_rate_limit_records) >= RATE_LIMIT_MAX_KEYS:
                    # Drop oldest 10% of entries if still at capacity
                    sorted_keys = sorted(_rate_limit_records.keys(), key=lambda k: _rate_limit_records[k][-1] if _rate_limit_records[k] else 0)
                    for k in sorted_keys[: max(1, len(_rate_limit_records) // 10)]:
                        del _rate_limit_records[k]

            # 3. Append current timestamp to all applicable keys
            for key in keys_to_check:
                existing = _rate_limit_records.get(key, [])
                active = [t for t in existing if t > window_start]
                active.append(now)
                _rate_limit_records[key] = active

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f'{{"event": "request_error", "request_id": "{request_id}", "method": "{request.method}", "path": "{request.url.path}", "duration_ms": {duration_ms:.2f}, "error": "{str(exc)}"}}')
        raise exc

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(f'{{"event": "request_completed", "request_id": "{request_id}", "method": "{request.method}", "path": "{request.url.path}", "status_code": {response.status_code}, "duration_ms": {duration_ms:.2f}}}')
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
    """Readiness probe checking database connectivity via SELECT 1."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: Database probe failed ({str(exc)})"
        )


@app.post("/api/ai/suggest-intent", response_model=IntentSuggestResponseSchema)
def api_suggest_intent(
    payload: IntentSuggestRequestSchema,
    current_user: User = Depends(get_current_user)
):
    """Suggests an operations intent category based on regex rules or fallback."""
    intent, source = suggest_ticket_intent(payload.title, payload.description)
    return {"intent": intent, "source": source}


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates user with email and password, returning a JWT access token.
    Raises 401 Unauthorized if invalid credentials.
    """
    user = db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

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

    total_count = query.count()
    tickets = query.options(defer(Ticket.description)).offset(offset).limit(limit).all()

    now = datetime.now(timezone.utc)
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
            "queue_score": t.queue_score if current_user.role != "Requester" else None,
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

    # 2. Intent suggestion if not provided
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
    is_emergency_bypass = (
        deadline_hours is not None and deadline_hours <= EMERGENCY_BYPASS_HOURS
    )

    if is_emergency_bypass:
        priority = "Urgent"
        ticket_status = "Escalated"
        routing_reason = (
            f"Tier-1 Emergency Bypass: effective deadline {deadline_hours:.1f}h <= {EMERGENCY_BYPASS_HOURS}h"
        )
        assigned_agent_id = DEFAULT_ESCALATION_MANAGER_ID

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves full ticket detail.
    - If requester belongs to another agency -> 403 Forbidden.
    - If requester belongs to same agency -> InternalNotes and side_conversations are withheld.
    - Staff members receive complete operations view.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Access control
    if current_user.role == "Requester" and ticket.agency_id != current_user.agency_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to tickets from another agency")

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

    queue_score = ticket.queue_score
    if queue_score is None:
        queue_score = calculate_queue_score_tier2(
            priority=ticket.priority,
            check_in_date=ticket.check_in_date,
            agency_tier=agency_tier,
            lcd_date=ticket.lcd_date,
            intent=ticket.intent,
            now=now
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


# ============================================================================
# 3. TICKET ACTIONS (ASSIGN, STATUS, ESCALATE, TRANSFER)
# ============================================================================

@app.post("/api/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: str,
    payload: TicketAssignSchema,
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
            Ticket.queue_score: ticket.queue_score,
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unassigns ticket returning it to triage atomically."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot unassign tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

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
            Ticket.queue_score: ticket.queue_score,
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

    if payload.version is not None and ticket.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {payload.version}."
        )

    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
    if payload.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid status transition from '{ticket.status}' to '{payload.status}'. Allowed: {allowed}"
        )

    old_status = ticket.status
    current_version = ticket.version
    now = datetime.now(timezone.utc)
    ticket.status = payload.status
    agency_tier = ticket.agency.tier if ticket.agency else None
    compute_ticket_urgency_fields(ticket, agency_tier=agency_tier, now=now)

    rowcount = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == current_version
    ).update(
        {
            Ticket.status: payload.status,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.queue_score: ticket.queue_score,
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
        payload={"ticket_id": ticket.id, "old_status": old_status, "new_status": payload.status}
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.status_changed",
        details={"old_status": old_status, "new_status": payload.status}
    )
    db.commit()

    return {"status": "success", "ticket_id": ticket.id, "old_status": old_status, "new_status": payload.status, "version": current_version + 1}


@app.post("/api/tickets/{ticket_id}/escalate")
def escalate_ticket(
    ticket_id: str,
    payload: TicketEscalateSchema,
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

    if payload.version is not None and ticket.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {payload.version}."
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
            Ticket.assigned_to: DEFAULT_ESCALATION_MANAGER_ID,
            Ticket.routing_reason: routing_reason,
            Ticket.effective_deadline_at: ticket.effective_deadline_at,
            Ticket.queue_score: ticket.queue_score,
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

    old_agent = ticket.assigned_to
    current_version = ticket.version

    if payload.version is not None and ticket.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Stale write. Ticket is at version {ticket.version}, expected {payload.version}."
        )

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
            Ticket.queue_score: ticket.queue_score,
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
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this ticket")
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


@app.get("/api/export/tickets.csv")
def export_tickets_csv(
    status: Optional[str] = None,
    agency_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Uncapped CSV data streaming export for ops beyond 3K-row UX barrier (MVP-6).
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

    query = db.query(Ticket)
    if status:
        query = query.filter(Ticket.status == status)
    if agency_id:
        query = query.filter(Ticket.agency_id == agency_id)
    if from_date:
        query = query.filter(Ticket.created_at >= from_date)
    if to_date:
        query = query.filter(Ticket.created_at <= to_date)

    query = query.order_by(Ticket.created_at.desc())

    def iter_csv():
        start_time = time.time()
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

            # Stream rows in chunks of 500 without loading all rows into RAM
            for ticket in query.yield_per(500):
                if time.time() - start_time > CSV_EXPORT_MAX_DURATION_SECONDS:
                    writer.writerow(["# [ABORTED: Export exceeded maximum duration limit]"])
                    yield output.getvalue()
                    break

                writer.writerow([
                    sanitize_csv_cell(ticket.id),
                    sanitize_csv_cell(ticket.tboh_id),
                    sanitize_csv_cell(ticket.agency_id),
                    sanitize_csv_cell(ticket.title),
                    sanitize_csv_cell(ticket.intent or ""),
                    sanitize_csv_cell(ticket.priority),
                    sanitize_csv_cell(ticket.status),
                    sanitize_csv_cell(ticket.check_in_date.isoformat() if ticket.check_in_date else ""),
                    sanitize_csv_cell(ticket.lcd_date.isoformat() if ticket.lcd_date else ""),
                    sanitize_csv_cell(ticket.assigned_to or ""),
                    sanitize_csv_cell(ticket.created_at.isoformat() if ticket.created_at else "")
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        finally:
            try:
                _export_semaphore.release()
            except ValueError:
                pass

    headers = {
        "Content-Disposition": "attachment; filename=opsdesk_tickets_export.csv",
        "Content-Type": "text/csv; charset=utf-8"
    }
    return StreamingResponse(iter_csv(), headers=headers, media_type="text/csv")

