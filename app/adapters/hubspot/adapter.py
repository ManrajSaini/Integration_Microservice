from collections.abc import Mapping

from app.adapters.hubspot.crm import HubSpotCrm
from app.adapters.hubspot.oauth import HubSpotOAuth
from app.models.schemas import CanonicalRecord, PageResult, TokenSet, WebhookEvent


class HubSpotAdapter:
    """Composes HubSpot's OAuth and CRM mechanics behind the ProviderAdapter
    interface — see architecture.md §2."""

    provider_name = "hubspot"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, verify_ssl: bool = True) -> None:
        self._oauth = HubSpotOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            verify_ssl=verify_ssl,
        )
        self._crm = HubSpotCrm(verify_ssl=verify_ssl)

    async def build_authorize_url(self, state: str) -> str:
        return await self._oauth.build_authorize_url(state)

    async def exchange_code_for_tokens(self, code: str) -> TokenSet:
        return await self._oauth.exchange_code_for_tokens(code)

    async def refresh_access_token(self, refresh_token: str) -> TokenSet:
        return await self._oauth.refresh_access_token(refresh_token)

    async def fetch_page(self, object_type: str, access_token: str, after: str | None) -> PageResult:
        return await self._crm.fetch_page(object_type, access_token, after)

    async def push_record(
        self, object_type: str, access_token: str, record: CanonicalRecord
    ) -> CanonicalRecord:
        raise NotImplementedError("Bidirectional sync is not yet implemented (Phase 10 bonus)")

    def verify_webhook_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        raise NotImplementedError("Webhook handling is implemented in Phase 7")

    def parse_webhook_events(self, raw_body: bytes) -> list[WebhookEvent]:
        raise NotImplementedError("Webhook handling is implemented in Phase 7")
