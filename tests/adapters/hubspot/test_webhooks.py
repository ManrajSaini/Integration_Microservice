import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from app.adapters.hubspot.webhooks import HubSpotWebhooks

CLIENT_SECRET = "shh-its-a-secret"


def _sign(method: str, uri: str, body: bytes, timestamp_ms: int) -> str:
    base_string = method.upper().encode() + uri.encode() + body + str(timestamp_ms).encode()
    digest = hmac.new(CLIENT_SECRET.encode(), base_string, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def test_valid_signature_passes():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    body = b'[{"eventId":1}]'
    timestamp = _now_ms()
    signature = _sign("POST", "/webhook", body, timestamp)

    result = webhooks.verify_signature(
        method="POST",
        request_uri="/webhook",
        headers={"X-HubSpot-Signature-v3": signature, "X-HubSpot-Request-Timestamp": str(timestamp)},
        raw_body=body,
    )

    assert result is True


def test_tampered_body_fails():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    original_body = b'[{"eventId":1}]'
    tampered_body = b'[{"eventId":2}]'
    timestamp = _now_ms()
    signature = _sign("POST", "/webhook", original_body, timestamp)

    result = webhooks.verify_signature(
        method="POST",
        request_uri="/webhook",
        headers={"X-HubSpot-Signature-v3": signature, "X-HubSpot-Request-Timestamp": str(timestamp)},
        raw_body=tampered_body,
    )

    assert result is False


def test_wrong_secret_fails():
    webhooks = HubSpotWebhooks(client_secret="a-different-secret")
    body = b'[{"eventId":1}]'
    timestamp = _now_ms()
    signature = _sign("POST", "/webhook", body, timestamp)

    result = webhooks.verify_signature(
        method="POST",
        request_uri="/webhook",
        headers={"X-HubSpot-Signature-v3": signature, "X-HubSpot-Request-Timestamp": str(timestamp)},
        raw_body=body,
    )

    assert result is False


def test_stale_timestamp_fails():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    body = b'[{"eventId":1}]'
    stale_timestamp = int((datetime.now(UTC) - timedelta(minutes=10)).timestamp() * 1000)
    signature = _sign("POST", "/webhook", body, stale_timestamp)

    result = webhooks.verify_signature(
        method="POST",
        request_uri="/webhook",
        headers={
            "X-HubSpot-Signature-v3": signature,
            "X-HubSpot-Request-Timestamp": str(stale_timestamp),
        },
        raw_body=body,
    )

    assert result is False


def test_missing_headers_fail():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)

    result = webhooks.verify_signature(
        method="POST", request_uri="/webhook", headers={}, raw_body=b"[]"
    )

    assert result is False


def test_parse_events_maps_fields_correctly():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    raw_body = json.dumps(
        [
            {
                "objectId": 1246965,
                "propertyName": "lifecyclestage",
                "propertyValue": "subscriber",
                "changeSource": "ACADEMY",
                "eventId": 3816279340,
                "subscriptionId": 25,
                "portalId": 33,
                "appId": 1160452,
                "occurredAt": 1462216307945,
                "subscriptionType": "contact.propertyChange",
                "attemptNumber": 0,
            }
        ]
    ).encode()

    events = webhooks.parse_events(raw_body)

    assert len(events) == 1
    event = events[0]
    assert event.event_id == "3816279340"
    assert event.object_id == "1246965"
    assert event.subscription_type == "contact.propertyChange"
    assert event.object_type == "contacts"  # resolved via legacy prefix fallback
    assert event.portal_id == "33"
    assert event.raw["propertyName"] == "lifecyclestage"


def test_parse_events_resolves_object_type_from_object_type_id():
    """Regression test: real HubSpot Projects-platform webhooks use the
    generic 'object.propertyChange' subscriptionType with a separate
    objectTypeId field (e.g. "0-1" for contacts) — not the legacy
    "contact.propertyChange" prefix format. See solve.md Phase 7 entry."""
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    raw_body = json.dumps(
        [
            {
                "eventId": 1765889350,
                "subscriptionId": 7662269,
                "portalId": 247279312,
                "appId": 51879189,
                "occurredAt": 1788597072520,
                "subscriptionType": "object.propertyChange",
                "attemptNumber": 0,
                "objectId": 546500061938,
                "objectTypeId": "0-1",
                "propertyName": "email",
                "propertyValue": "bhalli@hubspot.com",
                "changeSource": "CRM_UI",
                "sourceId": "userId:98499705",
                "isSensitive": False,
            }
        ]
    ).encode()

    events = webhooks.parse_events(raw_body)

    assert len(events) == 1
    assert events[0].object_type == "contacts"


def test_parse_events_unrecognized_object_type_id_yields_none():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    raw_body = json.dumps(
        [
            {
                "eventId": 1,
                "objectId": 1,
                "objectTypeId": "0-999",
                "subscriptionType": "object.propertyChange",
                "occurredAt": 1462216307945,
            }
        ]
    ).encode()

    events = webhooks.parse_events(raw_body)

    assert events[0].object_type is None


def test_parse_events_handles_batch_of_multiple():
    webhooks = HubSpotWebhooks(client_secret=CLIENT_SECRET)
    raw_body = json.dumps(
        [
            {
                "objectId": 1,
                "eventId": 100,
                "subscriptionType": "contact.creation",
                "occurredAt": 1462216307945,
            },
            {
                "objectId": 2,
                "eventId": 101,
                "subscriptionType": "deal.creation",
                "occurredAt": 1462216307946,
            },
        ]
    ).encode()

    events = webhooks.parse_events(raw_body)

    assert len(events) == 2
    assert events[0].object_id == "1"
    assert events[1].object_id == "2"
