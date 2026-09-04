import pytest

from app.errors import RateLimitedError, TransientProviderError, ValidationError
from app.orchestration.retry import make_provider_retry

# Zero wait so tests don't actually sleep through exponential backoff.
fast_retry = make_provider_retry(max_attempts=5, wait_initial=0, wait_max=0)


async def test_retries_until_success():
    calls = {"count": 0}

    @fast_retry
    async def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RateLimitedError("429")
        return "ok"

    result = await flaky()

    assert result == "ok"
    assert calls["count"] == 3


async def test_gives_up_after_max_attempts():
    calls = {"count": 0}

    @fast_retry
    async def always_fails():
        calls["count"] += 1
        raise TransientProviderError("503")

    with pytest.raises(TransientProviderError):
        await always_fails()

    assert calls["count"] == 5


async def test_non_retryable_error_propagates_immediately():
    calls = {"count": 0}

    @fast_retry
    async def bad_request():
        calls["count"] += 1
        raise ValidationError("400")

    with pytest.raises(ValidationError):
        await bad_request()

    assert calls["count"] == 1
