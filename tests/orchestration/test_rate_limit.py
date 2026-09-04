import asyncio

from app.orchestration.rate_limit import TokenBucket


async def test_acquire_does_not_block_within_capacity():
    bucket = TokenBucket(capacity=5, period_seconds=1)

    start = asyncio.get_event_loop().time()
    for _ in range(5):
        await bucket.acquire()
    elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 0.2


async def test_acquire_throttles_once_capacity_exhausted():
    bucket = TokenBucket(capacity=2, period_seconds=0.4)

    for _ in range(2):
        await bucket.acquire()

    start = asyncio.get_event_loop().time()
    await bucket.acquire()
    elapsed = asyncio.get_event_loop().time() - start

    assert elapsed > 0.1
