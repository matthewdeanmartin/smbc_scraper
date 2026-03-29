# test/test_sources/test_smbc_wiki.py
from __future__ import annotations

from typing import Optional

import httpx
import pytest

from smbc_scraper.sources.smbc_wiki import SmbcWikiScraper


class DummyHttpClient:
    async def get(self, url: str) -> Optional[httpx.Response]:
        raise AssertionError("HTTP should not be called in parser unit tests")

@pytest.fixture
def wiki_scraper() -> SmbcWikiScraper:
    return SmbcWikiScraper(http_client=DummyHttpClient())

class TestSmbcWikiScraper:
    def test_extract_section(self, wiki_scraper: SmbcWikiScraper):
        wikitext = """
== Transcript ==
Line 1
Line 2
== Votey ==
Bonus line
"""
        transcript = wiki_scraper._extract_section(wikitext, "Transcript")
        assert transcript == "Line 1\nLine 2"

        votey = wiki_scraper._extract_section(wikitext, "Votey")
        assert votey == "Bonus line"

    def test_extract_section_case_insensitive(self, wiki_scraper: SmbcWikiScraper):
        wikitext = "== TRANSCRIPT ==\nContent"
        assert wiki_scraper._extract_section(wikitext, "Transcript") == "Content"

    def test_extract_smbc_url_from_template(self, wiki_scraper: SmbcWikiScraper):
        wikitext = "{{Comic|url=https://www.smbc-comics.com/comic/test}}"
        assert wiki_scraper._extract_smbc_url(wikitext) == "https://www.smbc-comics.com/comic/test"

    def test_extract_smbc_url_fallback(self, wiki_scraper: SmbcWikiScraper):
        wikitext = "Random text https://www.smbc-comics.com/comic/slug more text"
        assert wiki_scraper._extract_smbc_url(wikitext) == "https://www.smbc-comics.com/comic/slug"

    def test_extract_smbc_url_from_title(self, wiki_scraper: SmbcWikiScraper):
        wikitext = "{{comic|title=2023-10-01}}"
        assert wiki_scraper._extract_smbc_url(wikitext) == "https://www.smbc-comics.com/comic/2023-10-01"

    @pytest.mark.asyncio
    async def test_fetch_and_parse_page_handles_missing(
        self, wiki_scraper: SmbcWikiScraper, monkeypatch
    ):
        async def fake_get(url: str):
            class FakeResponse:
                status_code = 200
                text = '{"error": {"code": "missingtitle"}}'
                def json(self):
                    return {"error": {"code": "missingtitle"}}
            return FakeResponse()

        monkeypatch.setattr(wiki_scraper.client, "get", fake_get)
        result = await wiki_scraper._fetch_and_parse_page("9999", 9999)
        assert result is None
