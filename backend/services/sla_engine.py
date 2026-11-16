from datetime import datetime
from typing import Optional, Dict, Any
from backend.config.sla_config import SLA_THRESHOLDS, SLA_COLORS

def effective_deadline_hours(
    check_in_date: datetime,
    lcd_date: Optional[datetime],
    intent: Optional[str],
    now: datetime
) -> float:
    """
    Computes effective deadline hours remaining.
    
    Rule:
      - If intent in {'Refund Request', 'Cancellation Inconvenience', 'Unclassified', None} and lcd_date is not None:
        effective urgency is min(check_in_hours, lcd_hours).
      - For all other operational intents (e.g. Emergency Check-in Assist, Voucher Resend,
        Date Amendment, Bedding / Room Preference):
        cancellation deadlines are inapplicable; effective urgency is strictly check_in_hours.
    """
    hours_to_checkin = (check_in_date - now).total_seconds() / 3600.0
    cancellation_intents = {"Refund Request", "Cancellation Inconvenience", "Unclassified", None}
    
    if intent in cancellation_intents and lcd_date is not None:
        hours_to_lcd = (lcd_date - now).total_seconds() / 3600.0
        return min(hours_to_checkin, hours_to_lcd)
    return hours_to_checkin

def evaluate_travel_sla(
    status: str,
    check_in_date: datetime,
    lcd_date: Optional[datetime],
    priority: str,
    *,
    intent: Optional[str] = None,
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Evaluates the Travel SLA for an operations case.
    
    Rules:
      1. If status is 'Resolved' or 'Closed', the SLA is STOPPED (Gray), timer freezes.
      2. If ticket is active, effective urgency is computed via effective_deadline_hours.
      3. Priority modifies the At-Risk threshold:
         - Urgent: warning threshold is AT_RISK_HOURS_URGENT (6.0h)
         - High: warning threshold is AT_RISK_HOURS_HIGH (4.0h)
         - Medium/Low: warning threshold is AT_RISK_HOURS_DEFAULT (2.0h)
      4. If effective_hours <= 0.0 -> BREACHED (Red)
      5. If 0.0 < effective_hours <= threshold -> AT_RISK (Amber)
      6. Otherwise -> NORMAL (Green)
    """
    if status in ["Resolved", "Closed"]:
        return {
            "status": "STOPPED",
            "color": SLA_COLORS["STOPPED"],
            "badge": f"SLA Stopped ({status})",
            "hours_remaining": None
        }

    if now is None:
        now = datetime.utcnow()

    effective_hours = effective_deadline_hours(
        check_in_date=check_in_date,
        lcd_date=lcd_date,
        intent=intent,
        now=now
    )

    # Priority dynamically adjusts the At-Risk threshold buffer
    if priority == "Urgent":
        at_risk_threshold = SLA_THRESHOLDS["AT_RISK_HOURS_URGENT"]
    elif priority == "High":
        at_risk_threshold = SLA_THRESHOLDS["AT_RISK_HOURS_HIGH"]
    else:
        at_risk_threshold = SLA_THRESHOLDS["AT_RISK_HOURS_DEFAULT"]

    if effective_hours <= SLA_THRESHOLDS["BREACHED_HOURS"]:
        return {
            "status": "BREACHED",
            "color": SLA_COLORS["BREACHED"],
            "badge": f"SLA Breached ({abs(effective_hours):.1f}h ago)",
            "hours_remaining": round(effective_hours, 2)
        }
    elif effective_hours <= at_risk_threshold:
        return {
            "status": "AT_RISK",
            "color": SLA_COLORS["AT_RISK"],
            "badge": f"At-Risk ({effective_hours:.1f}h to deadline)",
            "hours_remaining": round(effective_hours, 2)
        }
    else:
        return {
            "status": "NORMAL",
            "color": SLA_COLORS["NORMAL"],
            "badge": f"Normal ({effective_hours:.1f}h remaining)",
            "hours_remaining": round(effective_hours, 2)
        }
