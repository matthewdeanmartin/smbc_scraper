from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from smbc_scraper.sources.smbc import SmbcScraper


class DummyHttpClient:
    async def get(self, _url: str):
        raise AssertionError("HTTP should not be called in parser unit tests")


@pytest.fixture
def smbc_scraper(tmp_path: Path) -> SmbcScraper:
    return SmbcScraper(http_client=DummyHttpClient(), data_dir=str(tmp_path))


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
