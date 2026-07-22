import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event: str
    server_id: str
    sequence: int
    occurred_at: datetime
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)
    entity_type: str | None = None
    entity_id: str | None = None
    correlation_id: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionMessage(BaseModel):
    action: str
    events: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
