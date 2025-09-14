# # tests/sources/test_smbc.py
#
# import asyncio
# from datetime import date
# from pathlib import Path
#
# import pytest
# from smbc_scraper.core.http import HttpClient
# from smbc_scraper.sources.smbc import SmbcScraper
#
# # All tests in this module are marked as asyncio
# pytestmark = pytest.mark.asyncio
#
# # --- Fixtures ---
#
#
# @pytest.fixture(scope="module")
# async def http_client(tmp_path_factory) -> HttpClient:
#     """Provides a module-scoped HttpClient instance with a shared cache."""
#     cache_dir = tmp_path_factory.mktemp("http_cache")
#     client = HttpClient(cache_dir=str(cache_dir))
#     yield client
#     await client.close()
#
#
# # CORRECTED FIXTURE: Changed from 'def' to 'async def'
# @pytest.fixture
# async def smbc_scraper(http_client: HttpClient, tmp_path: Path) -> SmbcScraper:
#     """Provides a SmbcScraper instance for a single test."""
#     # Now, pytest-asyncio will correctly await the http_client fixture
#     # before passing the resolved HttpClient object here.
#     return SmbcScraper(http_client=http_client, data_dir=str(tmp_path))
#
#
# # REMOVED the explicit event_loop fixture. pytest-asyncio handles it.
#
#
# # --- HTML Content Fixtures for testing the parser in isolation ---
#
#
# @pytest.fixture(scope="module")
# async def modern_comic_html(http_client: HttpClient) -> str:
#     """Provides the raw HTML of a modern comic (ID 7641)."""
#     url = "https://www.smbc-comics.com/index.php?db=comics&id=7641"
#     response = await http_client.get(url)
#     assert response is not None
#     return response.text
#
#
# @pytest.fixture(scope="module")
# async def old_comic_html(http_client: HttpClient) -> str:
#     """Provides the raw HTML of a very old comic (ID 1)."""
#     url = "https://www.smbc-comics.com/index.php?db=comics&id=1"
#     response = await http_client.get(url)
#     assert response is not None
#     return response.text
#
#
# # --- Test Classes ---
#
# # (The rest of the test classes remain unchanged)
# class TestSmbcScraperParsing:
#     """Tests the _parse_page method with static HTML content."""
#
#     def test_parse_page_modern_comic(
#         self, smbc_scraper: SmbcScraper, modern_comic_html: str
#     ):
#         """
#         Verifies parsing of a modern comic with JSON-LD, main image, and votey.
#         """
#         comic_row, images_to_download = smbc_scraper._parse_page(
#             "https://www.smbc-comics.com/comic/critical", modern_comic_html
#         )
#
#         assert comic_row is not None
#         assert comic_row.slug == "critical"
#         assert comic_row.date == date(2024, 9, 1)
#         assert "Saturday Morning Breakfast Cereal - Critical" in comic_row.page_title
#         assert comic_row.hover_text is not None and len(comic_row.hover_text) > 0
#         assert comic_row.votey_text is not None and len(comic_row.votey_text) > 0
#
#         assert len(images_to_download) == 2
#         main_url, _ = images_to_download[0]
#         votey_url, _ = images_to_download[1]
#         assert main_url.endswith(".png")
#         assert "after.png" in votey_url
#
#     def test_parse_page_old_comic(self, smbc_scraper: SmbcScraper, old_comic_html: str):
#         """
#         Verifies parsing of a legacy comic page without JSON-LD.
#         """
#         comic_row, images_to_download = smbc_scraper._parse_page(
#             "https://www.smbc-comics.com/comic/2002-09-05", old_comic_html
#         )
#
#         assert comic_row is not None
#         assert comic_row.slug == "2002-09-05"
#         assert comic_row.date == date(2002, 9, 5)
#         assert comic_row.page_title == "Saturday Morning Breakfast Cereal - Chips"
#         assert comic_row.hover_text is not None and "first single panel comic" in comic_row.hover_text
#         assert comic_row.votey_text is None
#
#         assert len(images_to_download) == 2
#         assert "20020905-2.gif" in images_to_download[0][0]
#         assert "20020905-2after.png" in images_to_download[1][0]
#
#     def test_parse_page_invalid_html(self, smbc_scraper: SmbcScraper):
#         """Verifies graceful failure when parsing invalid/empty content."""
#         comic_row, images = smbc_scraper._parse_page(
#             "http://example.com/invalid", "<html><body><p>No comic here</p></body></html>"
#         )
#         assert comic_row is None
#         assert len(images) == 0
#
#
# class TestSmbcScraperIntegration:
#     """
#     Tests the scraper's methods that perform file and network I/O.
#     These tests are slower as they make live HTTP requests.
#     """
#
#     async def test_download_image_success(self, smbc_scraper: SmbcScraper):
#         """Verifies a real image can be downloaded and saved."""
#         image_url = "https://www.smbc-comics.com/comics/20240101.png"
#         target_path = smbc_scraper.data_dir / "test_image.png"
#
#         success = await smbc_scraper._download_image(image_url, target_path)
#
#         assert success is True
#         assert target_path.exists()
#         assert target_path.stat().st_size > 1000
#
#     async def test_download_image_skips_existing(
#         self, smbc_scraper: SmbcScraper, caplog
#     ):
#         """Verifies that an existing image is not re-downloaded."""
#         target_path = smbc_scraper.data_dir / "existing_image.png"
#         target_path.parent.mkdir(exist_ok=True)
#         target_path.touch()
#
#         success = await smbc_scraper._download_image("http://example.com/img", target_path)
#
#         assert success is True
#         assert "Image already exists, skipping" in caplog.text
#
#     async def test_scrape_one_comic(self, smbc_scraper: SmbcScraper, tmp_path: Path):
#         """
#         Performs an end-to-end test for a single comic ID, including
#         HTML fetch, parsing, and image downloads.
#         """
#         comic_id = 7500
#         comic_date = date(2024, 4, 26)
#         date_path = f"{comic_date.year}/{comic_date.month:02d}/{comic_date.day:02d}"
#
#         comic_row = await smbc_scraper._scrape_one_comic(comic_id)
#
#         assert comic_row is not None
#         assert comic_row.slug == "sentient"
#         assert comic_row.date == comic_date
#
#         html_path = tmp_path / "html" / date_path / "sentient.html"
#         assert html_path.exists()
#         assert html_path.stat().st_size > 1000
#
#         main_img_path = tmp_path / "images" / date_path / "sentient-main.png"
#         votey_img_path = tmp_path / "images" / date_path / "sentient-votey.png"
#         assert main_img_path.exists()
#         assert votey_img_path.exists()
#         assert main_img_path.stat().st_size > 1000
#         assert votey_img_path.stat().st_size > 1000
#
#     @pytest.mark.slow
#     async def test_scrape_id_range(self, smbc_scraper: SmbcScraper, tmp_path: Path):
#         """
#         Tests the top-level method with a small range of comic IDs.
#         This is marked as 'slow' as it makes multiple requests.
#         """
#         results = await smbc_scraper.scrape_id_range(start_id=10, end_id=11)
#
#         assert len(results) == 2
#
#         comic_10 = next(r for r in results if r.slug == "2002-09-26")
#         assert comic_10 is not None
#         assert comic_10.date == date(2002, 9, 26)
#         assert (tmp_path / "html/2002/09/26/2002-09-26.html").exists()
#         assert (tmp_path / "images/2002/09/26/2002-09-26-main.gif").exists()
#
#         comic_11 = next(r for r in results if r.slug == "2002-09-28")
#         assert comic_11 is not None
#         assert comic_11.date == date(2002, 9, 28)
#         assert (tmp_path / "html/2002/09/28/2002-09-28.html").exists()
#         assert (tmp_path / "images/2002/09/28/2002-09-28-main.gif").exists()