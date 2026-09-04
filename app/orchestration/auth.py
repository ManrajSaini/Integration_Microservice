import secrets
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.errors import AuthenticationError, TokenRefreshError, TransientProviderError
from app.adapters.hubspot.oauth import HubSpotOAuth
from app.config import settings
from app.db.models import Install
from app.db.repository import upsert_install

# Refresh proactively once less than this fraction of the token's original
# lifetime remains — never wait for a 401 (details.md §2 Step 3/4).
REFRESH_THRESHOLD_FRACTION = 0.2

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


def _is_near_expiry(install: Install) -> bool:
    now = datetime.now(UTC)
    expires_at = install.access_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    remaining = expires_at - now
    # HubSpot access tokens are always issued with a 1800s (30 min) TTL.
    threshold = timedelta(seconds=1800 * REFRESH_THRESHOLD_FRACTION)
    return remaining <= threshold


async def ensure_fresh_access_token(session: AsyncSession, install: Install) -> Install:
    """Refreshes the install's access token if it's near expiry. Proactive only —
    never triggered by a 401, per HubSpot's own guidance (details.md §2)."""
    if not _is_near_expiry(install):
        return install

    try:
        tokens = await hubspot_oauth.refresh_access_token(install.refresh_token)
    except TokenRefreshError:
        install.status = "needs_reauth"
        await session.commit()
        await session.refresh(install)
        raise

    return await upsert_install(session, hub_id=install.hub_id, tokens=tokens)
