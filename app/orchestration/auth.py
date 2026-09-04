import secrets

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.errors import AuthenticationError, TransientProviderError
from app.adapters.hubspot.oauth import HubSpotOAuth
from app.config import settings
from app.db.repository import upsert_install

_pending_states: set[str] = set()

hubspot_oauth = HubSpotOAuth(
    client_id=settings.hubspot_client_id,
    client_secret=settings.hubspot_client_secret,
    redirect_uri=settings.hubspot_redirect_uri,
    verify_ssl=settings.httpx_verify_ssl,
)


def generate_state() -> str:
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)
    return state


def consume_state(state: str) -> bool:
    """Returns True if state was pending (and consumes it), False otherwise."""
    if state in _pending_states:
        _pending_states.discard(state)
        return True
    return False


async def start_install() -> str:
    state = generate_state()
    return await hubspot_oauth.build_authorize_url(state)


async def complete_install(session: AsyncSession, code: str, state: str) -> str:
    """Exchanges the auth code for tokens and upserts the install. Returns hub_id."""
    if not consume_state(state):
        raise AuthenticationError("Invalid or expired OAuth state")

    try:
        tokens = await hubspot_oauth.exchange_code_for_tokens(code)
    except httpx.HTTPError as exc:
        raise TransientProviderError(str(exc)) from exc

    install = await upsert_install(session, hub_id=tokens.account_id, tokens=tokens)
    return install.hub_id
