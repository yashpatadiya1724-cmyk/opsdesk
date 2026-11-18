from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_INTENTS = Literal[
    "Refund Request",
    "Cancellation Inconvenience",
    "Date Amendment",
    "Bedding / Room Preference",
    "Voucher Resend",
    "Emergency Check-in Assist",
    "Unclassified",
]

VALID_TICKET_STATUSES = Literal[
    "New",
    "Open",
    "Pending",
    "Escalated",
    "Resolved",
    "Closed"
]

MESSAGE_TYPES = Literal[
    "PublicReply",
    "InternalNote"
]

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def normalize_utc_datetime(v: Any, tz_name: Optional[str] = None) -> datetime:
    if isinstance(v, str):
        val = v.strip()
        if val.endswith("Z") or val.endswith("z"):
            val = val[:-1]
            if not (val.endswith("+00:00") or re.search(r"[+-]\d{2}:\d{2}$", val)):
                val = val + "+00:00"
        dt = datetime.fromisoformat(val)
    elif isinstance(v, datetime):
        dt = v
    else:
        raise ValueError("Invalid datetime value")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        # Naive datetime/string: treat as local to hotel_timezone if specified, else UTC directly
        if tz_name and tz_name != "UTC":
            try:
                dt = dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                dt = dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)
        else:
            dt = dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)
    return dt

def to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

class TicketCreateSchema(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5, max_length=5000)
    tboh_id: str = Field(..., pattern=r"^TBOH-[A-Za-z0-9-]{3,30}$")
    priority: Literal["Low", "Medium", "High", "Urgent"] = "Medium"
    check_in_date: datetime
    lcd_date: Optional[datetime] = None
    hotel_timezone: Optional[str] = "UTC"
    intent: Optional[ALLOWED_INTENTS] = None
    agency_id: Optional[str] = None  # Ignored for Requesters, caller agency used instead

    @model_validator(mode="before")
    @classmethod
    def normalize_datetimes_with_timezone(cls, data: Any) -> Any:
        if isinstance(data, dict):
            tz_name = data.get("hotel_timezone") or "UTC"
            if "check_in_date" in data and data["check_in_date"] is not None:
                data["check_in_date"] = normalize_utc_datetime(data["check_in_date"], tz_name=tz_name)
            if "lcd_date" in data and data["lcd_date"] is not None:
                data["lcd_date"] = normalize_utc_datetime(data["lcd_date"], tz_name=tz_name)
        return data

    @field_validator("check_in_date", "lcd_date", mode="before")
    @classmethod
    def validate_and_normalize_datetimes(cls, v: Any) -> Any:
        if v is None:
            return None
        return normalize_utc_datetime(v)

class TicketAssignSchema(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)

class TicketStatusUpdateSchema(BaseModel):
    status: VALID_TICKET_STATUSES
    version: Optional[int] = Field(None, description="Expected ticket version for optimistic concurrency control")

class TicketEscalateSchema(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
    version: Optional[int] = Field(None, description="Expected ticket version for optimistic concurrency control")

class TicketTransferSchema(BaseModel):
    target_agent_id: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=1000)
    version: Optional[int] = Field(None, description="Expected ticket version for optimistic concurrency control")

class TicketLinkSuggestionSchema(BaseModel):
    bug_link: str = Field(..., min_length=3, max_length=200)

class MessageCreateSchema(BaseModel):
    message_type: MESSAGE_TYPES = Field(..., description="'PublicReply' or 'InternalNote'")
    content: str = Field(..., min_length=1, max_length=5000)

class SideThreadCreateSchema(BaseModel):
    supplier_name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=300)
    recipients: List[str] = Field(..., min_length=1, max_length=20)
    initial_message: str = Field(..., min_length=1, max_length=5000)

    @field_validator("recipients")
    @classmethod
    def validate_recipients_emails(cls, recipients: List[str]) -> List[str]:
        if len(recipients) > 20:
            raise ValueError("Maximum 20 recipients allowed")
        for email in recipients:
            if not EMAIL_REGEX.match(email):
                raise ValueError(f"Invalid email address format: {email}")
        return recipients

class SideThreadMessageCreateSchema(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)

class IntentSuggestRequestSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)

class IntentSuggestResponseSchema(BaseModel):
    intent: str
    source: str

class AgencySchema(BaseModel):
    id: str
    name: str
    country_code: str
    tier: Optional[str] = "standard"

class TicketResponseSchema(BaseModel):
    id: str
    tboh_id: str
    agency_id: str
    priority: str
    status: str
    assigned_to: Optional[str] = None
    routing_reason: Optional[str] = None
    intent: Optional[str] = None
    hotel_timezone: Optional[str] = "UTC"
    linked_tickets_count: Optional[int] = 0


