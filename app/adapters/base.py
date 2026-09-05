from collections.abc import Mapping
from typing import Protocol

from app.models.schemas import CanonicalRecord, PageResult, TokenSet, WebhookEvent


class ProviderAdapter(Protocol):
    """Interface every provider adapter (HubSpot, and future providers) implements.

    The orchestration engine only ever depends on this Protocol, never on a
    concrete adapter class — see architecture.md §2.
    """

    provider_name: str

    async def build_authorize_url(self, state: str) -> str: ...
    async def exchange_code_for_tokens(self, code: str) -> TokenSet: ...
    async def refresh_access_token(self, refresh_token: str) -> TokenSet: ...

    async def fetch_page(
        self, object_type: str, access_token: str, after: str | None
    ) -> PageResult: ...

    async def fetch_one(
        self, object_type: str, access_token: str, object_id: str
    ) -> CanonicalRecord: ...

    async def push_record(
        self, object_type: str, access_token: str, record: CanonicalRecord
    ) -> CanonicalRecord: ...

    def verify_webhook_signature(
        self, method: str, request_uri: str, headers: Mapping[str, str], raw_body: bytes
    ) -> bool: ...
    def parse_webhook_events(self, raw_body: bytes) -> list[WebhookEvent]: ...
