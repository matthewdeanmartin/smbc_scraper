# smbc_scraper/core/http.py

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from hishel import AsyncCacheTransport, AsyncFileStorage, Controller
from loguru import logger
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class RateLimiter:
    """A simple async rate limiter to ensure we don't hit servers too fast."""

    def __init__(self, rate: float = 1.0):
        self.period = 1.0 / rate
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_request_time
            if elapsed < self.period:
                await asyncio.sleep(self.period - elapsed)
            self.last_request_time = asyncio.get_event_loop().time()


class HttpClient:
    """A wrapper around httpx.AsyncClient providing caching, retries, and rate limiting."""

    def __init__(
        self,
        cache_dir: str,
        rate_limit: float = 1.0,
        user_agent: str = "SMBC-Scraper/1.0",
    ):
        self.rate_limiter = RateLimiter(rate_limit)

        # Define retry strategy
        self.retryer = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError)
            ),
            reraise=True,
        )

        # Set up caching transport
        transport = AsyncCacheTransport(
            transport=httpx.AsyncHTTPTransport(
                retries=0
            ),  # Retries handled by tenacity
            controller=Controller(cacheable_methods=["GET"]),
            storage=AsyncFileStorage(base_path=cache_dir),
        )

        self.client = httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": user_agent},
        )
        logger.info(
            f"HttpClient initialized. Rate limit: {rate_limit} req/s. Cache: {cache_dir}"
        )

    async def get(self, url: str) -> Optional[httpx.Response]:
        """Performs a rate-limited, retrying GET request."""
        await self.rate_limiter.wait()

        try:
            async for attempt in self.retryer:
                with attempt:
                    logger.debug(
                        f"GET {url} (Attempt {attempt.retry_state.attempt_number})"
                    )
                    response = await self.client.get(url)

                    # Raise for 429 (Too Many Requests) and 5xx errors to trigger retry
                    if response.status_code == 429 or response.status_code >= 500:
                        response.raise_for_status()

                    return response
        except RetryError as e:
            logger.error(f"Failed to fetch {url} after multiple retries: {e}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred fetching {url}: {e}")
            return None

        return None  # Should be unreachable

    async def close(self):
        """Closes the underlying httpx client."""
        await self.client.aclose()
        logger.info("HttpClient closed.")
