from app.errors import TokenRefreshError

from .conftest import make_page


def test_sync_unknown_hub_id_returns_404_envelope(client):
    response = client.post("/sync", json={"hub_id": "does-not-exist"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_sync_invalid_object_type_returns_400_envelope(client, seeded_install):
    response = client.post(
        "/sync", json={"hub_id": "12345", "object_types": ["not_a_real_type"]}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sync_happy_path_fetches_and_upserts(client, fake_adapter, seeded_install):
    fake_adapter.pages["contacts"] = [make_page("1", "contacts")]

    response = client.post("/sync", json={"hub_id": "12345", "object_types": ["contacts"]})

    assert response.status_code == 200
    body = response.json()
    assert body[0]["object_type"] == "contacts"
    assert body[0]["status"] == "completed"
    assert body[0]["records_upserted"] == 1


def test_sync_token_refresh_failure_returns_error_envelope_not_500(
    client, fake_adapter, seeded_install_near_expiry
):
    """Regression test: a proactive refresh that fails with invalid_grant during
    /sync must map to the standard error envelope, not an unhandled 500 — this
    is the gap the phase 0-5 drift audit found (see solve.md)."""
    fake_adapter.refresh_error = TokenRefreshError("refresh token is invalid, expired or revoked")

    response = client.post("/sync", json={"hub_id": "99999", "object_types": ["contacts"]})

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "TOKEN_REFRESH_FAILED"
    assert "correlation_id" in body["error"]
