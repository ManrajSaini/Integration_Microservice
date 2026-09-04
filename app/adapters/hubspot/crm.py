import logging
from datetime import datetime

import httpx

from app.adapters.errors import (
    AuthenticationError,
    NotFoundError,
    RateLimitedError,
    TransientProviderError,
    ValidationError,
)
from app.models.schemas import CanonicalRecord, PageResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hubapi.com"
PAGE_LIMIT = 100

# Properties requested per object type — details.md §3.
OBJECT_PROPERTIES: dict[str, tuple[str, ...]] = {
    "contacts": ("email", "firstname", "lastname", "phone", "company", "lifecyclestage"),
    "companies": ("name", "domain", "industry"),
    "deals": (
        "dealname",
        "dealstage",
        "pipeline",
        "amount",
        "closedate",
        "dealtype",
        "hubspot_owner_id",
    ),
}


class HubSpotCrm:
    """CRM object fetch/parse — details.md §3."""

    def __init__(self, verify_ssl: bool = True) -> None:
        self.verify_ssl = verify_ssl

    async def fetch_page(
        self, object_type: str, access_token: str, after: str | None
    ) -> PageResult:
        params: dict[str, str | int] = {
            "limit": PAGE_LIMIT,
            "properties": ",".join(OBJECT_PROPERTIES[object_type]),
        }
        if after is not None:
            params["after"] = after

        url = f"{BASE_URL}/crm/v3/objects/{object_type}"

        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            try:
                response = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {access_token}"}
                )
            except httpx.TransportError as exc:
                raise TransientProviderError(str(exc)) from exc

        _raise_for_status(response)

        payload = response.json()
        records = [_to_canonical_record(object_type, item) for item in payload.get("results", [])]
        next_after = payload.get("paging", {}).get("next", {}).get("after")

        return PageResult(records=records, next_after=next_after)


def _to_canonical_record(object_type: str, item: dict) -> CanonicalRecord:
    return CanonicalRecord(
        external_id=str(item["id"]),
        object_type=object_type,
        properties=item.get("properties", {}),
        created_at=_parse_timestamp(item.get("createdAt")),
        updated_at=_parse_timestamp(item.get("updatedAt")),
        archived=item.get("archived", False),
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = payload.get("message", f"HubSpot returned {response.status_code}")

    if response.status_code == 401:
        raise AuthenticationError(message)
    if response.status_code == 404:
        raise NotFoundError(message)
    if response.status_code == 429:
        raise RateLimitedError(message)
    if response.status_code >= 500:
        raise TransientProviderError(message)
    if response.status_code >= 400:
        raise ValidationError(message)
