from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HandoffInboxCaseStatus(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    CLOSED = "closed"


class HandoffInboxMessageSender(str, Enum):
    CLIENT = "client"
    AGENT = "agent"
    SYSTEM = "system"


class HandoffInboxChannel(str, Enum):
    WHATSAPP = "whatsapp"


class HandoffInboxOutboxStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class HandoffInboxLastMessageFrom(str, Enum):
    CLIENT = "client"
    AGENT = "agent"
    SYSTEM = "system"


class HandoffInboxCaseRecord(BaseModel):
    case_id: str
    client_phone: str
    client_name: Optional[str] = None
    tipo_consulta: Optional[str] = None
    status: HandoffInboxCaseStatus
    has_unread: bool = False
    last_message_from: Optional[HandoffInboxLastMessageFrom] = None
    handoff_context: Optional[str] = None
    last_client_message_at: Optional[datetime] = None
    last_agent_message_at: Optional[datetime] = None
    last_interaction_at: Optional[datetime] = None
    owner_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class HandoffInboxCaseProjection(BaseModel):
    case_id: str
    client_phone: str
    client_name: Optional[str] = None
    tipo_consulta: Optional[str] = None
    is_active: bool
    queue_position: Optional[int] = None
    status: HandoffInboxCaseStatus
    has_unread: bool
    last_message_from: Optional[HandoffInboxLastMessageFrom] = None
    handoff_context: Optional[str] = None
    last_client_message_at: Optional[datetime] = None
    last_agent_message_at: Optional[datetime] = None
    last_interaction_at: Optional[datetime] = None
    owner_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class HandoffInboxMessageRecord(BaseModel):
    message_id: str
    client_local_id: Optional[str] = None
    source_message_id: Optional[str] = None
    sender: HandoffInboxMessageSender
    channel: HandoffInboxChannel = HandoffInboxChannel.WHATSAPP
    text: str = Field(default="", max_length=4000)
    created_at: datetime
    updated_at: Optional[datetime] = None
    delivery_status: Optional[HandoffInboxOutboxStatus] = None


class HandoffInboxOutboxRecord(BaseModel):
    outbox_id: str
    case_id: str
    client_phone: str
    owner_email: str
    text: str = Field(..., min_length=1, max_length=4000)
    status: HandoffInboxOutboxStatus
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None


class HandoffInboxCaseDetail(BaseModel):
    case: HandoffInboxCaseProjection
    messages: list[HandoffInboxMessageRecord] = Field(default_factory=list)
    next_cursor: Optional[datetime] = None


class HandoffInboxSummary(BaseModel):
    total_open_cases: int
    active_count: int
    queued_count: int
    unread_count: int
    updated_at: Optional[datetime] = None


class HandoffInboxRetentionCutoffs(BaseModel):
    messages_before: datetime
    outbox_before: datetime
    cases_before: datetime


class HandoffInboxRetentionResult(BaseModel):
    dry_run: bool
    batch_limit: int
    cutoffs: HandoffInboxRetentionCutoffs
    cases_scanned: int = 0
    cases_skipped_missing_closed_at: int = 0
    cases_deleted: int = 0
    messages_deleted: int = 0
    outbox_deleted: int = 0


class HandoffInboxAutocloseCaseRecord(BaseModel):
    case_id: str
    client_phone: str
    prior_status: HandoffInboxCaseStatus
    last_client_message_at: Optional[datetime] = None
    last_agent_message_at: Optional[datetime] = None
    created_at: datetime
    last_interaction_at: datetime


class HandoffInboxAutocloseResult(BaseModel):
    dry_run: bool
    batch_limit: int
    cutoff_before: datetime
    cases_scanned: int = 0
    cases_eligible: int = 0
    cases_closed: int = 0
    eligible_cases: list[HandoffInboxAutocloseCaseRecord] = Field(default_factory=list)
    closed_cases: list[HandoffInboxAutocloseCaseRecord] = Field(default_factory=list)
