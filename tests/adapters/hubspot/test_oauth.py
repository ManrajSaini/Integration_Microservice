import httpx
import pytest
import respx

from app.adapters.hubspot.oauth import TOKEN_URL, HubSpotOAuth
from app.errors import TokenRefreshError

oauth = HubSpotOAuth(
    client_id="client-123",
    client_secret="secret-abc",
    redirect_uri="http://localhost:8000/oauth/callback",
)


async def test_build_authorize_url_includes_required_params():
    url = await oauth.build_authorize_url(state="xyz")

    assert url.startswith("https://app.hubspot.com/oauth/authorize?")
    assert "client_id=client-123" in url
    assert "state=xyz" in url
    assert "redirect_uri=" in url


@respx.mock
async def test_exchange_code_for_tokens_success():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "token_type": "bearer",
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "hub_id": 12345,
                "scopes": ["oauth", "crm.objects.contacts.read"],
                "expires_in": 1800,
            },
        )
    )

    tokens = await oauth.exchange_code_for_tokens(code="one-time-code")

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.expires_in == 1800
    assert "oauth" in tokens.scopes
    assert tokens.account_id == "12345"


@respx.mock
async def test_refresh_access_token_success():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "token_type": "bearer",
                "access_token": "at-2",
                "refresh_token": "rt-1",
                "hub_id": 12345,
                "scopes": ["oauth"],
                "expires_in": 1800,
            },
        )
    )

    tokens = await oauth.refresh_access_token(refresh_token="rt-1")

    assert tokens.access_token == "at-2"


@respx.mock
async def test_refresh_access_token_invalid_grant_raises_token_refresh_error():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "refresh token is invalid, expired or revoked",
                "status": "BAD_REFRESH_TOKEN",
                "message": "refresh token is invalid, expired or revoked",
            },
        )
    )

    with pytest.raises(TokenRefreshError):
        await oauth.refresh_access_token(refresh_token="dead-token")
