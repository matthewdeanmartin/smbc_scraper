from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import httpx
import pytest

from smbc_scraper.models import ComicRow
from smbc_scraper.sources.smbc import (
    IncrementalScrapeState,
    SmbcScraper,
    resolve_incremental_start_id,
    save_incremental_state,
)


class DummyHttpClient:
    async def get(self, url: str) -> Optional[httpx.Response]:
        raise AssertionError("HTTP should not be called in parser unit tests")


@pytest.fixture
def smbc_scraper(tmp_path: Path) -> SmbcScraper:
    return SmbcScraper(http_client=DummyHttpClient(), data_dir=str(tmp_path))


def build_comic_row(slug: str, day: int) -> ComicRow:
    return ComicRow(
        url=f"https://www.smbc-comics.com/comic/{slug}",
        slug=slug,
        date=date(2024, 9, day),
        page_title=slug.title(),
        source="smbc",
    )


class TestSmbcScraperParsing:
    def test_parse_page_downloads_votey_once(
        self, smbc_scraper: SmbcScraper, tmp_path: Path
    ):
        html = """
        <html>
          <head>
            <title>Saturday Morning Breakfast Cereal - Critical</title>
            <script type="application/ld+json">
              {
                "datePublished": "2024-09-01T00:00:00Z",
                "url": "https://www.smbc-comics.com/comic/critical"
              }
            </script>
          </head>
          <body>
            <div id="comic">
              <img id="cc-comic" src="/comics/critical.png" title="hover text" />
            </div>
            <img id="aftercomic" src="/comics/criticalafter.png" title="bonus text" />
          </body>
        </html>
        """

        comic_row, images_to_download = smbc_scraper._parse_page(
            "https://www.smbc-comics.com/comic/critical", html
        )

        assert comic_row is not None
        assert comic_row.slug == "critical"
        assert comic_row.date == date(2024, 9, 1)
        assert comic_row.hover_text == "hover text"
        assert comic_row.votey_text == "bonus text"
        assert images_to_download == [
            (
                "https://www.smbc-comics.com/comics/critical.png",
                tmp_path / "images" / "2024" / "09" / "01" / "critical-main.png",
            ),
            (
                "https://www.smbc-comics.com/comics/criticalafter.png",
                tmp_path / "images" / "2024" / "09" / "01" / "critical-votey.png",
            ),
        ]

    def test_parse_page_can_infer_date_from_image_url(
        self, smbc_scraper: SmbcScraper, tmp_path: Path
    ):
        html = """
        <html>
          <head>
            <title>Saturday Morning Breakfast Cereal - Chips</title>
            <link rel="canonical" href="https://www.smbc-comics.com/comic/chips" />
          </head>
          <body>
            <div id="comic">
              <img src="/comics/20020905-2.gif" title="first hover" />
            </div>
          </body>
        </html>
        """

        comic_row, images_to_download = smbc_scraper._parse_page(
            "https://www.smbc-comics.com/index.php?db=comics&id=1", html
        )

        assert comic_row is not None
        assert comic_row.slug == "chips"
        assert comic_row.date == date(2002, 9, 5)
        assert images_to_download == [
            (
                "https://www.smbc-comics.com/comics/20020905-2.gif",
                tmp_path / "images" / "2002" / "09" / "05" / "chips-main.gif",
            )
        ]

    def test_parse_page_preserves_undated_comics_with_misc_paths(
        self, smbc_scraper: SmbcScraper, tmp_path: Path
    ):
        html = """
        <html>
          <head>
            <title>Saturday Morning Breakfast Cereal - Mystery</title>
            <link rel="canonical" href="https://www.smbc-comics.com/comic/mystery" />
          </head>
          <body>
            <div id="comic">
              <img src="/comics/mystery.png" alt="mystery hover" />
            </div>
            <img id="aftercomic" src="/comics/mysteryafter.png" alt="mystery bonus" />
          </body>
        </html>
        """

        comic_row, images_to_download = smbc_scraper._parse_page(
            "https://www.smbc-comics.com/comic/mystery", html
        )

        assert comic_row is not None
        assert comic_row.slug == "mystery"
        assert comic_row.date is None
        assert comic_row.hover_text == "mystery hover"
        assert comic_row.votey_text == "mystery bonus"
        assert images_to_download == [
            (
                "https://www.smbc-comics.com/comics/mystery.png",
                tmp_path / "images" / "misc" / "mystery-main.png",
            ),
            (
                "https://www.smbc-comics.com/comics/mysteryafter.png",
                tmp_path / "images" / "misc" / "mystery-votey.png",
            ),
        ]


class TestSmbcIncrementalState:
    def test_resolve_incremental_start_id_uses_saved_state(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        save_incremental_state(
            state_path, IncrementalScrapeState(last_scraped_id=1234)
        )

        start_id, state = resolve_incremental_start_id(state_path)

        assert start_id == 1235
        assert state == IncrementalScrapeState(last_scraped_id=1234)

    def test_resolve_incremental_start_id_requires_bootstrap(self, tmp_path: Path):
        with pytest.raises(ValueError, match="No incremental state file found"):
            resolve_incremental_start_id(tmp_path / "missing-state.json")


class TestSmbcIncrementalAndBackfill:
    @pytest.mark.asyncio
    async def test_discover_latest_legacy_id_finds_boundary(
        self, smbc_scraper: SmbcScraper, monkeypatch: pytest.MonkeyPatch
    ):
        async def fake_latest_slug():
            return "latest"

        async def fake_get_row(probe_id: int):
            slug = "latest" if probe_id >= 37 else f"older-{probe_id}"
            return build_comic_row(slug, 1)

        monkeypatch.setattr(smbc_scraper, "get_latest_comic_slug", fake_latest_slug)
        monkeypatch.setattr(smbc_scraper, "_get_row_for_legacy_id", fake_get_row)

        latest_id = await smbc_scraper.discover_latest_legacy_id(initial_probe_id=64)

        assert latest_id == 37

    @pytest.mark.asyncio
    async def test_scrape_full_archive_uses_discovered_latest_id(
        self, smbc_scraper: SmbcScraper, monkeypatch: pytest.MonkeyPatch
    ):
        async def fake_discover_latest():
            return 42

        async def fake_scrape_range(start_id: int, end_id: int):
            assert start_id == 1
            assert end_id == 42
            return [build_comic_row("forty-two", 1)]

        monkeypatch.setattr(
            smbc_scraper, "discover_latest_legacy_id", fake_discover_latest
        )
        monkeypatch.setattr(smbc_scraper, "scrape_id_range", fake_scrape_range)

        rows, latest_id = await smbc_scraper.scrape_full_archive()

        assert latest_id == 42
        assert [row.slug for row in rows] == ["forty-two"]

    @pytest.mark.asyncio
    async def test_scrape_incremental_stops_after_bounded_misses(
        self, smbc_scraper: SmbcScraper, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[int] = []
        available_rows = {
            5: build_comic_row("five", 5),
            7: build_comic_row("seven", 7),
        }

        async def fake_scrape_one(comic_id: int):
            calls.append(comic_id)
            return available_rows.get(comic_id)

        monkeypatch.setattr(smbc_scraper, "_scrape_one_comic", fake_scrape_one)

        rows, last_successful_id = await smbc_scraper.scrape_incremental(
            start_id=5, stop_after_missing=2
        )

        assert [row.slug for row in rows] == ["five", "seven"]
        assert last_successful_id == 7
        assert calls == [5, 6, 7, 8, 9]

    @pytest.mark.asyncio
    async def test_backfill_images_skips_existing_files(
        self, smbc_scraper: SmbcScraper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        source_csv = tmp_path / "smbc_ground_truth.csv"
        source_csv.write_text(
            "url,slug,comic_text,hover_text,votey_text,date,page_title,source,transcript_quality\n"
            "https://www.smbc-comics.com/comic/critical,critical,,,,2024-09-01,Critical,smbc,\n",
            encoding="utf-8",
        )

        html = """
        <html>
          <head>
            <title>Saturday Morning Breakfast Cereal - Critical</title>
            <script type="application/ld+json">
              {
                "datePublished": "2024-09-01T00:00:00Z",
                "url": "https://www.smbc-comics.com/comic/critical"
              }
            </script>
          </head>
          <body>
            <div id="comic">
              <img id="cc-comic" src="/comics/critical.png" title="hover text" />
            </div>
            <img id="aftercomic" src="/comics/criticalafter.png" title="bonus text" />
          </body>
        </html>
        """

        existing_main_path = (
            tmp_path / "images" / "2024" / "09" / "01" / "critical-main.png"
        )
        existing_main_path.parent.mkdir(parents=True, exist_ok=True)
        existing_main_path.write_bytes(b"already-here")

        async def fake_get(_url: str):
            return SimpleNamespace(
                status_code=200,
                url="https://www.smbc-comics.com/comic/critical",
                text=html,
            )

        downloaded_paths: list[Path] = []

        async def fake_download(_url: str, path: Path) -> bool:
            downloaded_paths.append(path)
            return True

        monkeypatch.setattr(smbc_scraper.client, "get", fake_get)
        monkeypatch.setattr(smbc_scraper, "_download_image", fake_download)

        downloaded = await smbc_scraper.backfill_images(
            source_csv_path=source_csv, concurrency=1
        )

        assert downloaded == 1
        assert downloaded_paths == [
            tmp_path / "images" / "2024" / "09" / "01" / "critical-votey.png"
        ]
