import httpx
import pytest
import respx

from app.adapters.hubspot.crm import BASE_URL, HubSpotCrm
from app.errors import NotFoundError, RateLimitedError

crm = HubSpotCrm()


@respx.mock
async def test_fetch_page_parses_records_and_next_after():
    respx.get(f"{BASE_URL}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "1",
                        "properties": {"email": "a@example.com", "firstname": "Ada"},
                        "createdAt": "2026-01-01T00:00:00Z",
                        "updatedAt": "2026-01-02T00:00:00Z",
                        "archived": False,
                    }
                ],
                "paging": {"next": {"after": "33452"}},
            },
        )
    )

    page = await crm.fetch_page("contacts", access_token="at-1", after=None)

    assert len(page.records) == 1
    assert page.records[0].external_id == "1"
    assert page.records[0].properties["email"] == "a@example.com"
    assert page.next_after == "33452"


@respx.mock
async def test_fetch_page_no_paging_next_means_last_page():
    respx.get(f"{BASE_URL}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(200, json={"results": [], "paging": {}})
    )

    page = await crm.fetch_page("contacts", access_token="at-1", after="999")

    assert page.records == []
    assert page.next_after is None


@respx.mock
async def test_fetch_page_429_raises_rate_limited_error():
    respx.get(f"{BASE_URL}/crm/v3/objects/deals").mock(
        return_value=httpx.Response(429, json={"status": "error", "message": "rate limited"})
    )

    with pytest.raises(RateLimitedError):
        await crm.fetch_page("deals", access_token="at-1", after=None)


@respx.mock
async def test_fetch_page_404_raises_not_found_error():
    respx.get(f"{BASE_URL}/crm/v3/objects/companies").mock(
        return_value=httpx.Response(404, json={"status": "error", "message": "not found"})
    )

    with pytest.raises(NotFoundError):
        await crm.fetch_page("companies", access_token="at-1", after=None)
