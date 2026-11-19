from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from backend.config.routing_config import (
    REGION_MAPPING,
    DEFAULT_FALLBACK_REGION,
    PRIORITY_SCORES,
    CHECKIN_URGENCY_MODIFIERS,
    AGENCY_TIER_MULTIPLIERS
)
from backend.services.sla_engine import effective_deadline_hours, to_utc_aware

class CandidateAgent:
    """Lightweight representation of an agent for routing evaluations."""
    def __init__(self, id: str, name: str, region: str, is_available: bool, active_ticket_count: int = 0):
        self.id = id
        self.name = name
        self.region = region
        self.is_available = is_available
        self.active_ticket_count = active_ticket_count

def select_agent_tier1(
    agency_country_code: str,
    candidate_agents: List[CandidateAgent]
) -> Tuple[Optional[str], str]:
    """
    Tier 1 Routing: Agent Selection
    Selects the best suited agent using exactly 3 factors:
      1. Agent Availability (is_available == True)
      2. Regional Affinity (matches agency country's region)
      3. Active Workload (fewest active tickets; tie broken by ID)
    
    Returns:
      (agent_id, routing_reason_string)
    """
    target_region = REGION_MAPPING.get(agency_country_code.upper(), DEFAULT_FALLBACK_REGION)
    
    # 1. Filter by availability
    available_agents = [a for a in candidate_agents if a.is_available]
    if not available_agents:
        return None, f"Unassigned to Triage Queue [Tier-1 Rule: No agents currently available across any region]"

    # 2. Filter by regional match
    regional_agents = [a for a in available_agents if a.region == target_region]
    
    # Pool fallback if regional desk has no available agents
    if not regional_agents:
        # Fallback to any available agent
        available_agents.sort(key=lambda a: (a.active_ticket_count, a.id))
        chosen = available_agents[0]
        reason = (
            f"Assigned to {chosen.name} [Tier-1 Fallback: Region={target_region} pool had 0 available agents; "
            f"selected {chosen.region} agent with lowest workload ({chosen.active_ticket_count} active cases)]"
        )
        return chosen.id, reason

    # 3. Workload balancing among regional agents (tie broken by agent ID)
    regional_agents.sort(key=lambda a: (a.active_ticket_count, a.id))
    chosen = regional_agents[0]
    reason = (
        f"Assigned to {chosen.name} [Tier-1 Rule: Region={target_region} match, "
        f"Availability=True, Workload={chosen.active_ticket_count} active cases]"
    )
    return chosen.id, reason


def calculate_queue_score_tier2(
    priority: str,
    check_in_date: datetime,
    *args,
    agency_tier: Optional[str] = None,
    lcd_date: Optional[datetime] = None,
    intent: Optional[str] = None,
    now: Optional[datetime] = None
) -> float:
    """
    Tier 2 Routing: Queue Ordering / Ranking
    Orders the triage/assigned queue using 2 factors:
      1. Priority ranking (Urgent > High > Medium > Low)
      2. Time Window / Urgency Proximity (closer effective deadline = higher queue position)
         - For cancellation intents (Refund/Cancellation/Unclassified), effective deadline = min(check_in, lcd)
         - For other operational intents, effective deadline strictly = check_in
      3. Agency Tier Multiplier (Platinum: 1.3x, Gold: 1.15x, Standard: 1.0x)
    
    Returns:
      numerical queue score (higher = should be handled first)
    """
    if agency_tier is None and args:
        agency_tier = args[0]

    if now is None:
        now = datetime.now(timezone.utc)
        
    hours_remaining = effective_deadline_hours(
        check_in_date=check_in_date,
        lcd_date=lcd_date,
        intent=intent,
        now=now
    )
    
    # Priority base score
    base_score = PRIORITY_SCORES.get(priority, PRIORITY_SCORES["Medium"])
    
    # Time window modifier based on effective deadline hours
    if hours_remaining <= 2.0:
        time_modifier = CHECKIN_URGENCY_MODIFIERS["IMMINENT_2H"]
    elif hours_remaining <= 6.0:
        time_modifier = CHECKIN_URGENCY_MODIFIERS["SAME_DAY_6H"]
    elif hours_remaining <= 24.0:
        time_modifier = CHECKIN_URGENCY_MODIFIERS["NEXT_DAY_24H"]
    else:
        time_modifier = 0.0
        
    score = base_score + time_modifier
    if agency_tier is not None:
        multiplier = AGENCY_TIER_MULTIPLIERS.get(agency_tier.lower(), 1.0)
        score *= multiplier

    return score


def compute_ticket_urgency_fields(
    ticket: Any,
    agency_tier: Optional[str] = None,
    now: Optional[datetime] = None
) -> Any:
    """
    Computes and sets urgency fields on a ticket:
      - effective_deadline_at: effective deadline UTC datetime
      - queue_score: numerical priority queue score
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if agency_tier is None and hasattr(ticket, "agency") and ticket.agency:
        agency_tier = getattr(ticket.agency, "tier", None)

    cancellation_intents = {"Refund Request", "Cancellation Inconvenience", "Unclassified", None}
    cid_aware = to_utc_aware(ticket.check_in_date)
    lcd_aware = to_utc_aware(ticket.lcd_date) if ticket.lcd_date is not None else None

    if ticket.intent in cancellation_intents and lcd_aware is not None:
        if cid_aware is not None:
            effective_deadline = min(cid_aware, lcd_aware)
        else:
            effective_deadline = lcd_aware
    else:
        effective_deadline = cid_aware

    queue_score = calculate_queue_score_tier2(
        priority=ticket.priority,
        check_in_date=ticket.check_in_date,
        agency_tier=agency_tier,
        lcd_date=ticket.lcd_date,
        intent=ticket.intent,
        now=now
    )

    ticket.priority_weight = PRIORITY_SCORES.get(ticket.priority, PRIORITY_SCORES["Medium"])
    ticket.effective_deadline_at = effective_deadline
    ticket.queue_score = queue_score
    return ticket


def get_sql_queue_score_expr(now: datetime, dialect_name: str = "sqlite"):
    """
    Constructs a SQL expression computing the dynamic queue score at read-time inside ORDER BY
    without issuing any UPDATE statements.
    Formula: (priority_weight + time_modifier) * tier_multiplier
    Values from backend/config/routing_config.py:
      - Priority scores: Urgent=1000.0, High=500.0, Medium=200.0, Low=50.0
      - Time modifiers: <=2h: 2000.0 (IMMINENT_2H), <=6h: 800.0 (SAME_DAY_6H), <=24h: 300.0 (NEXT_DAY_24H)
      - Tier multipliers: platinum=1.3, gold=1.15, standard=1.0
    """
    from sqlalchemy import case, literal, func
    from backend.app.models import Ticket, Agency

    # 1. Base Priority Weight
    priority_fallback = case(
        (Ticket.priority == "Urgent", literal(PRIORITY_SCORES["Urgent"])),
        (Ticket.priority == "High", literal(PRIORITY_SCORES["High"])),
        (Ticket.priority == "Medium", literal(PRIORITY_SCORES["Medium"])),
        (Ticket.priority == "Low", literal(PRIORITY_SCORES["Low"])),
        else_=literal(PRIORITY_SCORES["Medium"])
    )
    if hasattr(Ticket, "priority_weight"):
        priority_weight_expr = func.coalesce(Ticket.priority_weight, priority_fallback)
    else:
        priority_weight_expr = priority_fallback

    # 2. Hours Remaining from effective_deadline_at to now
    now_utc = to_utc_aware(now) or datetime.now(timezone.utc)
    if dialect_name == "postgresql":
        hours_diff_expr = func.extract("epoch", Ticket.effective_deadline_at - now_utc) / 3600.0
    else:
        # SQLite
        now_iso = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        hours_diff_expr = (func.julianday(Ticket.effective_deadline_at) - func.julianday(now_iso)) * 24.0

    # 3. Time Urgency Modifier
    time_modifier_expr = case(
        (Ticket.effective_deadline_at.is_(None), literal(0.0)),
        (hours_diff_expr <= 2.0, literal(CHECKIN_URGENCY_MODIFIERS["IMMINENT_2H"])),
        (hours_diff_expr <= 6.0, literal(CHECKIN_URGENCY_MODIFIERS["SAME_DAY_6H"])),
        (hours_diff_expr <= 24.0, literal(CHECKIN_URGENCY_MODIFIERS["NEXT_DAY_24H"])),
        else_=literal(0.0)
    )

    # 4. Agency Tier Multiplier
    tier_multiplier_expr = case(
        (func.lower(Agency.tier) == "platinum", literal(AGENCY_TIER_MULTIPLIERS["platinum"])),
        (func.lower(Agency.tier) == "gold", literal(AGENCY_TIER_MULTIPLIERS["gold"])),
        else_=literal(AGENCY_TIER_MULTIPLIERS["standard"])
    )

    return (priority_weight_expr + time_modifier_expr) * tier_multiplier_expr


def refresh_stale_queue_scores(db: Any, now: Optional[datetime] = None) -> int:
    """
    Refreshes queue_score on active tickets whose scores have shifted
    due to time advancing across urgency proximity windows (24h, 6h, 2h).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    from backend.app.models import Ticket, Agency
    agency_map = {a[0]: a[1] for a in db.query(Agency.id, Agency.tier).all()}
    active_tickets = db.query(Ticket).filter(
        Ticket.status.in_(["New", "Open", "Pending", "Escalated"])
    ).all()

    updated = 0
    for t in active_tickets:
        agency_tier = agency_map.get(t.agency_id)
        old_score = t.queue_score
        compute_ticket_urgency_fields(t, agency_tier=agency_tier, now=now)
        if t.queue_score != old_score:
            updated += 1

    if updated > 0:
        db.commit()
    return updated

