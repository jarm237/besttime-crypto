import pytest
import asyncio
import aiohttp
from btc_scraper.exchanges.binance import create_robust_client_session, SyncResolver

@pytest.mark.anyio
async def test_create_robust_client_session_uses_threaded_resolver():
    """Verify that create_robust_client_session creates a session with ThreadedResolver."""
    async with create_robust_client_session() as session:
        assert isinstance(session.connector._resolver, aiohttp.ThreadedResolver)

def test_sync_resolver_alias():
    """Verify SyncResolver derives from aiohttp.ThreadedResolver."""
    assert issubclass(SyncResolver, aiohttp.ThreadedResolver)

@pytest.mark.anyio
async def test_robust_client_session_http_request():
    """Verify robust client session performs successful HTTP GET request without DNS error."""
    timeout = aiohttp.ClientTimeout(total=5.0)
    async with create_robust_client_session(timeout=timeout) as session:
        async with session.get("https://api.binance.com/api/v3/time") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "serverTime" in data
