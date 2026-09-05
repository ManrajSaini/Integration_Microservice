from datetime import datetime

from pydantic import BaseModel


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    scopes: list[str] = []
    account_id: str


class CanonicalRecord(BaseModel):
    """Provider-agnostic representation of one CRM object (contact/company/deal)."""

    external_id: str
    object_type: str
    properties: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False


class PageResult(BaseModel):
    """One page of a paginated CRM object list."""

    records: list[CanonicalRecord]
    next_after: str | None = None


class WebhookEvent(BaseModel):
    """Provider-agnostic representation of one webhook event."""

    event_id: str
    subscription_type: str
    object_type: str | None = None
    object_id: str
    occurred_at: datetime
    portal_id: str | None = None
    raw: dict
