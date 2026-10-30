from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    intervention_id: int
    kind: str
    idempotency_key: str
    status: str
    recipient: str | None
    subject: str
    attempts: int
    last_error: str | None
    created_at: dt.datetime
    dispatched_at: dt.datetime | None
    sent_at: dt.datetime | None


class AutomationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    event_type: str
    level: str
    message: str
    job_id: int | None
    notification_id: int | None


class ClaimResponse(BaseModel):
    should_send: bool
    status: str
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    reason: str | None = None


class NotificationAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["sent", "failed"]
    error: str | None = Field(None, max_length=2000)


class JobFailureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str = Field(max_length=2000)


class IntegrationStatus(BaseModel):
    name: str
    state: Literal["active", "demo", "not_configured", "fallback", "unavailable"]
    detail: str


class AutomationStatus(BaseModel):
    demo_mode: bool
    integrations: list[IntegrationStatus]
    metrics: dict[str, Any]
    recent_events: list[AutomationEventRead]
    notifications: list[NotificationRead]
