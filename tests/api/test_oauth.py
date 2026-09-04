from app.errors import AuthenticationError
from app.models.schemas import TokenSet
from app.orchestration import auth as auth_module


def test_authorize_redirects_to_hubspot(client):
    response = client.get("/oauth/authorize", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://app.hubspot.com/oauth/authorize")


def test_callback_completes_install(client, fake_adapter):
    fake_adapter.exchange_result = TokenSet(
        access_token="at-1", refresh_token="rt-1", expires_in=1800, scopes=["oauth"], account_id="12345"
    )
    state = auth_module.generate_state()

    response = client.get(f"/oauth/callback?code=abc&state={state}")

    assert response.status_code == 200
    assert response.json() == {"status": "installed", "hub_id": "12345"}


def test_callback_with_invalid_state_returns_error_envelope(client):
    response = client.get("/oauth/callback?code=abc&state=never-issued")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTHENTICATION_ERROR"
    assert "correlation_id" in body["error"]


def test_callback_exchange_failure_returns_error_envelope_not_raw_traceback(client, fake_adapter):
    fake_adapter.exchange_error = AuthenticationError("invalid code")
    state = auth_module.generate_state()

    response = client.get(f"/oauth/callback?code=bad&state={state}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"
