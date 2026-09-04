from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.adapters.errors import RateLimitedError, TransientProviderError


def make_provider_retry(max_attempts: int = 5, wait_initial: float = 1, wait_max: float = 30):
    return retry(
        retry=retry_if_exception_type((RateLimitedError, TransientProviderError)),
        wait=wait_exponential_jitter(initial=wait_initial, max=wait_max),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )


with_provider_retry = make_provider_retry()
