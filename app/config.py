from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    hubspot_redirect_uri: str = "http://localhost:8000/oauth/callback"

    database_url: str = "sqlite+aiosqlite:///./local.db"

    app_base_url: str = "http://localhost:8000"

    # Local-dev escape hatch for networks with TLS-inspecting proxies (e.g.
    # corporate Netskope/Zscaler). Never set false outside local dev.
    httpx_verify_ssl: bool = True


settings = Settings()
