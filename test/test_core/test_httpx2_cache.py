"""Verify the HTTPX2/Hishel boundary without external service requests."""

from pathlib import Path

import httpx2
import pytest
from tenacity import wait_none

from smbc_scraper.core.http import HttpClient


@pytest.mark.asyncio
async def test_cached_get_retains_httpx2_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            200, text="café", headers={"Cache-Control": "max-age=60"}
        )

    monkeypatch.setattr(
        httpx2, "AsyncHTTPTransport", lambda **kwargs: httpx2.MockTransport(handle)
    )
    client = HttpClient(tmp_path, rate_limit=1000)
    try:
        first = await client.get("https://example.test/comic")
        second = await client.get("https://example.test/comic")
        assert isinstance(first, httpx2.Response)
        assert isinstance(second, httpx2.Response)
        assert first.text == second.text == "café"
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_httpx2_status_errors_trigger_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(500, text="unavailable")

    monkeypatch.setattr(
        httpx2, "AsyncHTTPTransport", lambda **kwargs: httpx2.MockTransport(handle)
    )
    client = HttpClient(tmp_path, rate_limit=1000)
    client.retryer.wait = wait_none()
    try:
        assert await client.get("https://example.test/comic") is None
        assert len(calls) == 3
    finally:
        await client.close()
