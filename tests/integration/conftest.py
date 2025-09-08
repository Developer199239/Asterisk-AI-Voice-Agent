import pytest_asyncio
import asyncio
from redis.asyncio import Redis

# Fixture to provide a Redis client for integration tests
@pytest_asyncio.fixture(scope="module")
async def redis_client():
    client = Redis.from_url("redis://redis-test:6379", decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()
