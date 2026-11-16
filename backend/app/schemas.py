from datetime import datetime, timezone
import re
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator

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

def normalize_utc_datetime(v: Any) -> datetime:
    if isinstance(v, str):
        val = v.strip()
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        dt = datetime.fromisoformat(val)
    elif isinstance(v, datetime):
        dt = v
    else:
        raise ValueError("Invalid datetime value")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

class TicketCreateSchema(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5, max_length=5000)
    tboh_id: str = Field(..., pattern=r"^TBOH-[A-Za-z0-9-]{3,30}$")
    priority: Literal["Low", "Medium", "High", "Urgent"] = "Medium"
    check_in_date: datetime
    lcd_date: Optional[datetime] = None
    intent: Optional[ALLOWED_INTENTS] = None
    agency_id: Optional[str] = None  # Ignored for Requesters, caller agency used instead

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

class TicketEscalateSchema(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)

class TicketTransferSchema(BaseModel):
    target_agent_id: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=1000)

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
