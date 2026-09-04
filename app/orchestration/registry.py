from functools import lru_cache

from app.adapters.base import ProviderAdapter
from app.adapters.hubspot.adapter import HubSpotAdapter
from app.config import settings

# The only place a concrete adapter class is named outside its own module —
# per constitution.md §2, api/ must go through this factory (not a concrete
# adapter class) and orchestration/ itself must do the same everywhere except
# here.


@lru_cache
def get_adapter(provider: str = "hubspot") -> ProviderAdapter:
    if provider == "hubspot":
        return HubSpotAdapter(
            client_id=settings.hubspot_client_id,
            client_secret=settings.hubspot_client_secret,
            redirect_uri=settings.hubspot_redirect_uri,
            verify_ssl=settings.httpx_verify_ssl,
        )
    raise ValueError(f"Unknown provider: {provider}")
