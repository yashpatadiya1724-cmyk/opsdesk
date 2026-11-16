import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.app.database import get_db
from backend.app.models import (
    User, Agency, Ticket, TicketLink, TicketMessage,
    SideConversation, SideConversationRecipient, SideConversationMessage,
    TicketTheme, EventOutbox, AuditLog
)
from backend.app.schemas import (
    TicketCreateSchema, TicketAssignSchema, TicketStatusUpdateSchema,
    TicketEscalateSchema, TicketTransferSchema, MessageCreateSchema,
    SideThreadCreateSchema, SideThreadMessageCreateSchema,
    IntentSuggestRequestSchema, IntentSuggestResponseSchema
)
from backend.app.auth import get_current_user
from backend.app.events import emit_outbox_event, record_audit_log
from backend.config.routing_config import (
    DEFAULT_ESCALATION_MANAGER_ID,
    REGION_MAPPING
)
from backend.services.sla_engine import evaluate_travel_sla
from backend.services.routing_engine import (
    CandidateAgent, select_agent_tier1, calculate_queue_score_tier2
)
from backend.services.intent_classifier import suggest_ticket_intent

app = FastAPI(
    title="OpsDesk: B2B Travel Operations Case Management API",
    description="Operational case management platform tailored for high-volume B2B travel operations.",
    version="1.0.0"
)

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

@app.post("/api/ai/suggest-intent", response_model=IntentSuggestResponseSchema)
def api_suggest_intent(
    payload: IntentSuggestRequestSchema,
    current_user: User = Depends(get_current_user)
):
    """Suggests an operations intent category based on regex rules or fallback."""
    intent, source = suggest_ticket_intent(payload.title, payload.description)
    return {"intent": intent, "source": source}


# ============================================================================
# 2. TICKETS ENDPOINTS
# ============================================================================

@app.get("/api/tickets")
def list_tickets(
    view: str = Query("triage", description="View filter: triage, my_queue, by_region, by_intent, linked"),
    intent: Optional[str] = Query(None, description="Optional intent category filter"),
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
                query = query.order_by(Ticket.intent, Ticket.created_at.desc())
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
            else:
                query = query.order_by(Ticket.intent, Ticket.created_at.desc())
        elif view == "triage":
            # Active queue: strictly unassigned active tickets
            query = query.filter(
                Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
                Ticket.assigned_to.is_(None)
            )

    now = datetime.utcnow()

    # Note: At demo scale (5,000 records), computing SLA and queue_score across filtered candidate tickets in Python
    # and sorting globally prior to offset/limit slicing provides exact queue prioritization without requiring database-specific
    # procedural extensions. For production scale (millions of records), queue_score is maintained via indexed column or Rust/Go scoring sidecar.
    if view in ["triage", "my_queue"]:
        all_candidates = query.all()
        total_count = len(all_candidates)

        scored_tickets = []
        for t in all_candidates:
            sla = evaluate_travel_sla(
                status=t.status,
                check_in_date=t.check_in_date,
                lcd_date=t.lcd_date,
                priority=t.priority,
                intent=t.intent,
                now=now
            )
            queue_score = calculate_queue_score_tier2(
                priority=t.priority,
                check_in_date=t.check_in_date,
                lcd_date=t.lcd_date,
                intent=t.intent,
                now=now
            )
            scored_tickets.append((queue_score, sla, t))

        # Global sort by queue_score descending, tie-breaking by created_at
        scored_tickets.sort(key=lambda x: (x[0], -x[2].created_at.timestamp() if x[2].created_at else 0), reverse=True)

        paginated_slice = scored_tickets[offset : offset + limit]

        results = []
        for queue_score, sla, t in paginated_slice:
            results.append({
                "id": t.id,
                "tboh_id": t.tboh_id,
                "agency_id": t.agency_id,
                "title": t.title,
                "intent": t.intent,
                "priority": t.priority,
                "status": t.status,
                "check_in_date": t.check_in_date.isoformat(),
                "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
                "assigned_to": t.assigned_to if current_user.role != "Requester" else None,
                "routing_reason": t.routing_reason if current_user.role != "Requester" else None,
                "sla": sla,
                "queue_score": queue_score if current_user.role != "Requester" else None,
                "created_at": t.created_at.isoformat()
            })

        return {"total": total_count, "tickets": results}

    else:
        total_count = query.count()
        tickets = query.offset(offset).limit(limit).all()

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
            queue_score = calculate_queue_score_tier2(
                priority=t.priority,
                check_in_date=t.check_in_date,
                lcd_date=t.lcd_date,
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
                "check_in_date": t.check_in_date.isoformat(),
                "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
                "assigned_to": t.assigned_to if current_user.role != "Requester" else None,
                "routing_reason": t.routing_reason if current_user.role != "Requester" else None,
                "sla": sla,
                "queue_score": queue_score if current_user.role != "Requester" else None,
                "created_at": t.created_at.isoformat()
            })

        return {"total": total_count, "tickets": results}


@app.post("/api/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreateSchema,
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
    """
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
    now = datetime.utcnow()

    new_ticket = Ticket(
        id=ticket_id,
        tboh_id=payload.tboh_id,
        agency_id=resolved_agency_id,
        title=payload.title,
        description=payload.description,
        intent=resolved_intent,
        priority=payload.priority,
        status="Open" if assigned_agent_id else "New",
        check_in_date=payload.check_in_date,
        lcd_date=payload.lcd_date,
        assigned_to=assigned_agent_id,
        routing_reason=routing_reason,
        created_at=now,
        updated_at=now
    )
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

    db.commit()

    return {
        "id": new_ticket.id,
        "tboh_id": new_ticket.tboh_id,
        "agency_id": new_ticket.agency_id,
        "status": new_ticket.status,
        "assigned_to": new_ticket.assigned_to,
        "routing_reason": new_ticket.routing_reason,
        "intent": new_ticket.intent,
        "linked_tickets_count": len(prior_tickets)
    }


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

    now = datetime.utcnow()
    sla = evaluate_travel_sla(
        status=ticket.status,
        check_in_date=ticket.check_in_date,
        lcd_date=ticket.lcd_date,
        priority=ticket.priority,
        intent=ticket.intent,
        now=now
    )
    queue_score = calculate_queue_score_tier2(
        priority=ticket.priority,
        check_in_date=ticket.check_in_date,
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
        "check_in_date": ticket.check_in_date.isoformat(),
        "lcd_date": ticket.lcd_date.isoformat() if ticket.lcd_date else None,
        "assigned_to": ticket.assigned_to if current_user.role != "Requester" else None,
        "routing_reason": ticket.routing_reason if current_user.role != "Requester" else None,
        "sla": sla,
        "queue_score": queue_score if current_user.role != "Requester" else None,
        "linked_ticket_ids": linked_tickets,
        "messages": messages,
        "side_conversations": side_threads,
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
    """Assigns an operations ticket to a designated staff member."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot assign tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    target_agent = db.query(User).filter(User.id == payload.agent_id).first()
    if not target_agent or target_agent.role not in ["Agent", "Lead", "EscalationManager"]:
        raise HTTPException(status_code=400, detail="Target agent must be internal staff")

    old_agent = ticket.assigned_to
    ticket.assigned_to = payload.agent_id
    if ticket.status == "New":
        ticket.status = "Open"
    ticket.updated_at = datetime.utcnow()

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

    return {"status": "success", "ticket_id": ticket.id, "assigned_to": ticket.assigned_to}


@app.post("/api/tickets/{ticket_id}/unassign")
def unassign_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unassigns ticket returning it to triage."""
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot unassign tickets")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    old_agent = ticket.assigned_to
    ticket.assigned_to = None
    ticket.updated_at = datetime.utcnow()

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

    return {"status": "success", "ticket_id": ticket.id, "assigned_to": None}


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
    Returns 409 Conflict if transition is not permitted.
    """
    if current_user.role == "Requester":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only internal operations staff can update ticket status"
        )

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
    if payload.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid status transition from '{ticket.status}' to '{payload.status}'. Allowed: {allowed}"
        )

    old_status = ticket.status
    ticket.status = payload.status
    ticket.updated_at = datetime.utcnow()

    emit_outbox_event(
        db=db,
        event_type="ticket.status_changed",
        ticket_id=ticket.id,
        agency_id=ticket.agency_id,
        visibility="public",
        payload={"ticket_id": ticket.id, "old_status": old_status, "new_status": ticket.status}
    )
    record_audit_log(
        db=db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        action="ticket.status_changed",
        details={"old_status": old_status, "new_status": ticket.status}
    )
    db.commit()

    return {"status": "success", "ticket_id": ticket.id, "old_status": old_status, "new_status": ticket.status}


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
    - Public outbox payload excludes internal free-text reason to prevent operational leakage.
    """
    if current_user.role == "Requester":
        raise HTTPException(status_code=403, detail="Forbidden: Requesters cannot escalate tickets directly")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, [])
    if "Escalated" not in allowed and ticket.status != "Escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot escalate ticket from current status '{ticket.status}'"
        )

    old_status = ticket.status
    old_assignee = ticket.assigned_to

    ticket.status = "Escalated"
    ticket.assigned_to = DEFAULT_ESCALATION_MANAGER_ID
    ticket.routing_reason = f"Escalated to Escalation Manager ({DEFAULT_ESCALATION_MANAGER_ID})"
    ticket.updated_at = datetime.utcnow()

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
        "routing_reason": ticket.routing_reason
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
    ticket.assigned_to = payload.target_agent_id
    ticket.routing_reason = f"Transferred from {old_agent} to {payload.target_agent_id}"
    ticket.updated_at = datetime.utcnow()

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
        "assigned_to": ticket.assigned_to,
        "routing_reason": ticket.routing_reason,
        "side_conversations_preserved": side_convo_count,
        "total_recipients_preserved": recipients_count
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
    now = datetime.utcnow()

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
    now = datetime.utcnow()

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
    now = datetime.utcnow()

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
