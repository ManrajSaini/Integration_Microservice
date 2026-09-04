import logging
from urllib.parse import urlencode

import httpx

from app.adapters.errors import AuthenticationError, TokenRefreshError, TransientProviderError
from app.models.schemas import TokenSet

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/2026-03/token"

REQUIRED_SCOPES = (
    "oauth",
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
)


class HubSpotOAuth:
    """OAuth2 mechanics for the HubSpot adapter — details.md §2."""

    def __init__(
        self, client_id: str, client_secret: str, redirect_uri: str, verify_ssl: bool = True
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            logger.warning(
                "SSL verification is DISABLED for HubSpot API calls — local dev only, never use in production"
            )

    async def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "scope": " ".join(REQUIRED_SCOPES),
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> TokenSet:
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        return await self._request_tokens(body)

    async def refresh_access_token(self, refresh_token: str) -> TokenSet:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            return await self._request_tokens(body)
        except AuthenticationError as exc:
            raise TokenRefreshError(str(exc)) from exc

    async def _request_tokens(self, body: dict[str, str]) -> TokenSet:
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            try:
                response = await client.post(TOKEN_URL, data=body)
            except httpx.TransportError as exc:
                raise TransientProviderError(str(exc)) from exc

        if response.status_code >= 500:
            raise TransientProviderError(f"HubSpot token endpoint returned {response.status_code}")

        payload = response.json()

        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error_description") or "OAuth request failed"
            raise AuthenticationError(message)

        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            expires_in=payload["expires_in"],
            scopes=payload.get("scopes", []),
            account_id=str(payload["hub_id"]),
        )
