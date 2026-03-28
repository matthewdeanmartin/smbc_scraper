from __future__ import annotations

from pathlib import Path

import pytest

from smbc_scraper.sources.ohnorobot import OhNoRobotScraper


class DummyHttpClient:
    async def get(self, _url: str):
        raise AssertionError("HTTP should not be called in parser unit tests")


@pytest.fixture
def ohnorobot_scraper() -> OhNoRobotScraper:
    return OhNoRobotScraper(http_client=DummyHttpClient())


class TestOhNoRobotScraper:
    def test_get_identifier_from_url_supports_modern_and_legacy_formats(
        self, ohnorobot_scraper: OhNoRobotScraper
    ):
        assert (
            ohnorobot_scraper._get_identifier_from_url(
                "https://www.smbc-comics.com/index.php?db=comics&id=42"
            )
            == "42"
        )
        assert (
            ohnorobot_scraper._get_identifier_from_url("/comic/astronomy")
            == "astronomy"
        )

    def test_parse_page_normalizes_relative_urls(
        self, ohnorobot_scraper: OhNoRobotScraper
    ):
        html = """
        <ul>
          <li>
            <blockquote>
              <a class="searchlink" href="/comic/astronomy">Astronomy</a>
              <div class="tinylink">metadata</div>
              <p>ignored summary</p>
              First line
              <br />
              Second line
            </blockquote>
          </li>
        </ul>
        """

        results = ohnorobot_scraper._parse_page(html)

        assert len(results) == 1
        assert str(results[0].url) == "https://www.smbc-comics.com/comic/astronomy"
        assert results[0].slug == "astronomy"
        comic_text = results[0].comic_text or ""
        assert "First line" in comic_text
        assert "Second line" in comic_text
        assert "ignored summary" not in comic_text

    @pytest.mark.asyncio
    async def test_scrape_generates_queries_from_existing_csv_titles(
        self,
        ohnorobot_scraper: OhNoRobotScraper,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        (tmp_path / "smbc_ground_truth.csv").write_text(
            "url,page_title\n"
            "https://www.smbc-comics.com/comic/1,"
            "Saturday Morning Breakfast Cereal - Big Robot Theory!\n"
            "https://www.smbc-comics.com/comic/2,"
            "Saturday Morning Breakfast Cereal - Big Robot Theory!\n"
            "https://www.smbc-comics.com/comic/3,"
            "Saturday Morning Breakfast Cereal - Another Test Case\n",
            encoding="utf-8",
        )

        captured_queries: list[str] = []

        async def fake_run_queries(queries: list[str]):
            captured_queries.extend(queries)
            return []

        monkeypatch.setattr(ohnorobot_scraper, "_run_queries", fake_run_queries)

        results = await ohnorobot_scraper.scrape(tmp_path, limit=10)

        assert results == []
        assert captured_queries == ["Another Test Case", "Big Robot Theory"]
