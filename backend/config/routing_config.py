# Routing Engine Configuration
# Country to regional support hub mapping
REGION_MAPPING = {
    "AE": "MEA", "SA": "MEA", "QA": "MEA", "OM": "MEA", "BH": "MEA",
    "IN": "APAC", "SG": "APAC", "TH": "APAC", "MY": "APAC", "ID": "APAC",
    "UK": "EUR", "GB": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR"
}

DEFAULT_FALLBACK_REGION = "APAC"

# Escalation Manager Configuration (configurable assignment target)
DEFAULT_ESCALATION_MANAGER_ID = "USR-103"  # Vikram Malhotra (EscalationManager)

# Tier 2: Queue Priority Score Weights (Assumption)
# Higher score = higher position in agent queue
PRIORITY_SCORES = {
    "Urgent": 1000.0,
    "High": 500.0,
    "Medium": 200.0,
    "Low": 50.0
}

# Time Window urgency modifiers for queue ordering (Assumption)
CHECKIN_URGENCY_MODIFIERS = {
    "IMMINENT_2H": 2000.0,  # Check-in in <= 2 hours
    "SAME_DAY_6H": 800.0,   # Check-in in <= 6 hours
    "NEXT_DAY_24H": 300.0   # Check-in in <= 24 hours
}

AGENCY_TIER_MULTIPLIERS = {
    "platinum": 1.3,
    "gold": 1.15,
    "standard": 1.0,
}

EMERGENCY_BYPASS_HOURS = 4

