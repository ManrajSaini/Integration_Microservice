import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from app.models.schemas import WebhookEvent

logger = logging.getLogger(__name__)

MAX_SIGNATURE_AGE = timedelta(minutes=5)

SIGNATURE_HEADER = "X-HubSpot-Signature-v3"
TIMESTAMP_HEADER = "X-HubSpot-Request-Timestamp"


class HubSpotWebhooks:
    """v3 signature verification and event parsing — details.md §5."""

    def __init__(self, client_secret: str) -> None:
        self.client_secret = client_secret

    def verify_signature(
        self, method: str, request_uri: str, headers: Mapping[str, str], raw_body: bytes
    ) -> bool:
        signature = headers.get(SIGNATURE_HEADER)
        timestamp_header = headers.get(TIMESTAMP_HEADER)
        if not signature or not timestamp_header:
            return False

        if not _is_timestamp_fresh(timestamp_header):
            return False

        expected = _compute_signature(self.client_secret, method, request_uri, raw_body, timestamp_header)
        return hmac.compare_digest(expected, signature)

    def parse_events(self, raw_body: bytes) -> list[WebhookEvent]:
        payload = json.loads(raw_body)
        return [_to_webhook_event(item) for item in payload]


def _is_timestamp_fresh(timestamp_header: str) -> bool:
    try:
        timestamp_ms = int(timestamp_header)
    except ValueError:
        return False
    sent_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return datetime.now(UTC) - sent_at <= MAX_SIGNATURE_AGE


def _compute_signature(
    client_secret: str, method: str, request_uri: str, raw_body: bytes, timestamp_header: str
) -> str:
    base_string = method.upper().encode() + request_uri.encode() + raw_body + timestamp_header.encode()
    digest = hmac.new(client_secret.encode(), base_string, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


# HubSpot's standard CRM object-type IDs (Projects-platform webhook payloads
# carry these in objectTypeId; legacy payloads instead prefix subscriptionType
# with the object name, e.g. "contact.propertyChange" — support both).
_OBJECT_TYPE_ID_TO_LOCAL: dict[str, str] = {
    "0-1": "contacts",
    "0-2": "companies",
    "0-3": "deals",
}
_LEGACY_SUBSCRIPTION_PREFIX_TO_LOCAL: dict[str, str] = {
    "contact": "contacts",
    "company": "companies",
    "deal": "deals",
}


def _resolve_object_type(item: dict) -> str | None:
    object_type_id = item.get("objectTypeId")
    if object_type_id is not None:
        resolved = _OBJECT_TYPE_ID_TO_LOCAL.get(str(object_type_id))
        if resolved is not None:
            return resolved

    prefix = item["subscriptionType"].split(".", 1)[0]
    return _LEGACY_SUBSCRIPTION_PREFIX_TO_LOCAL.get(prefix)


def _to_webhook_event(item: dict) -> WebhookEvent:
    return WebhookEvent(
        event_id=str(item["eventId"]),
        subscription_type=item["subscriptionType"],
        object_type=_resolve_object_type(item),
        object_id=str(item["objectId"]),
        occurred_at=datetime.fromtimestamp(item["occurredAt"] / 1000, tz=UTC),
        portal_id=str(item.get("portalId")) if item.get("portalId") is not None else None,
        raw=item,
    )
