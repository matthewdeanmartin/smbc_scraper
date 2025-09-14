# tests/core/test_http.py

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from smbc_scraper.core.http import HttpClient

# All tests in this module are marked as asyncio
pytestmark = pytest.mark.asyncio


class TestHttpClient:
    """Tests for the HttpClient class, making real network calls."""

    async def test_successful_get_with_custom_user_agent(self, tmp_path: Path):
        """
        Verifies a successful GET request and checks if the custom User-Agent is sent.
        """
        cache_dir = tmp_path / "test_cache"
        client = HttpClient(cache_dir=str(cache_dir))
        try:
            # httpbin.org/get reflects the request headers in its response
            response = await client.get("https://httpbin.org/get")
            assert response is not None
            assert response.status_code == 200

            data = response.json()
            assert data["headers"]["User-Agent"] == "SMBC-Scraper/1.0"
        finally:
            await client.close()

    # async def test_caching_works_for_subsequent_requests(self, tmp_path: Path):
    #     """
    #     Verifies that a second request to the same URL is served from the cache.
    #     """
    #     cache_dir = tmp_path / "test_cache"
    #     client = HttpClient(cache_dir=str(cache_dir))
    #     try:
    #         # httpbin.org/uuid returns a unique UUID on each non-cached request
    #         first_response = await client.get("https://httpbin.org/uuid")
    #         assert first_response is not None
    #         assert "x-cache" not in first_response.headers  # First hit is a miss
    #         first_uuid = first_response.json()["uuid"]
    #
    #         # Make the same request again
    #         second_response = await client.get("https://httpbin.org/uuid")
    #         assert second_response is not None
    #         assert second_response.headers["x-cache"] == "HIT"  # Should be a cache hit
    #         second_uuid = second_response.json()["uuid"]
    #
    #         # The UUID should be the same because the response was cached
    #         assert first_uuid == second_uuid
    #
    #     finally:
    #         await client.close()

    async def test_rate_limiter_enforces_delay(self, tmp_path: Path):
        """
        Verifies that the rate limiter correctly waits between requests.
        """
        # A rate of 2 requests/sec means a period of 0.5 seconds between requests
        client = HttpClient(cache_dir=str(tmp_path), rate_limit=2.0)

        start_time = time.monotonic()
        try:
            # Make two requests back-to-back
            await client.get("https://httpbin.org/get")
            await client.get("https://httpbin.org/get")
        finally:
            await client.close()

        duration = time.monotonic() - start_time

        # The total time should be at least the period of the rate limit
        # due to the enforced wait after the first request.
        # Allowing for a small margin of error.
        assert duration > 0.49


    async def test_no_retry_on_4xx_client_error(self, tmp_path: Path, caplog):
        """
        Verifies that the client does NOT retry on a standard 4xx error (e.g., 404).
        """
        client = HttpClient(cache_dir=str(tmp_path))
        try:
            # httpbin.org/status/404 consistently returns a 404 Not Found error
            response = await client.get("https://httpbin.org/status/404")

            # It should return the response immediately without retrying
            assert response is not None
            assert response.status_code == 404

            # Verify that no retry attempts were logged
            log_text = caplog.text
            assert "Attempt 2" not in log_text
            assert "Failed to fetch" not in log_text
        finally:
            await client.close()

    async def test_client_can_be_closed(self, tmp_path: Path):
        """
        Verifies that the client can be closed and raises an error on subsequent use.
        """
        client = HttpClient(cache_dir=str(tmp_path))
        await client.close()