from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from backend.config.routing_config import (
    REGION_MAPPING,
    DEFAULT_FALLBACK_REGION,
    PRIORITY_SCORES,
    CHECKIN_URGENCY_MODIFIERS
)
from backend.services.sla_engine import effective_deadline_hours

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
    *,
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
    
    Returns:
      numerical queue score (higher = should be handled first)
    """
    if now is None:
        now = datetime.utcnow()
        
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
        
    return base_score + time_modifier
