from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from loguru import logger
from rich.progress import Progress
from selectolax.parser import HTMLParser

from smbc_scraper.core.files import get_html_path, get_image_path
from smbc_scraper.core.http import HttpClient
from smbc_scraper.models import ComicRow


class SmbcScraper:
    """
    Ground-truth scraper for the official smbc-comics.com website.

    This class crawls comics within an ID range, extracts metadata from each page,
    and downloads the main and 'votey' (bonus) panel images.
    """

    BASE_URL = "https://www.smbc-comics.com"
    IMAGE_DATE_RE = re.compile(
        r"(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])"
    )

    def __init__(self, http_client: HttpClient, data_dir: str):
        self.client = http_client
        self.data_dir = Path(data_dir)

    @staticmethod
    def _extract_slug(url: str) -> str:
        """Extract a slug from /comic/<slug> or legacy index.php?id=<id> URLs."""
        parsed_url = urlparse(url)
        path = parsed_url.path.rstrip("/")
        if path and path != "/":
            slug = path.split("/")[-1]
            if slug and slug != "index.php":
                return slug

        query_params = parse_qs(parsed_url.query)
        if comic_ids := query_params.get("id"):
            return comic_ids[0]

        return url.rstrip("/").rsplit("/", maxsplit=1)[-1]

    @classmethod
    def _infer_date_from_image_url(cls, image_url: str) -> Optional[date]:
        """Infer a publication date from an image URL like /comics/20020905-2.gif."""
        match = cls.IMAGE_DATE_RE.search(urlparse(image_url).path)
        if not match:
            return None

        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )

    async def _download_image(self, url: str, path: Path) -> bool:
        """Downloads a single image to the specified path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            logger.trace(f"Image already exists, skipping: {path}")
            return True

        logger.debug(f"Attempting to download image from URL: {url}")
        response = await self.client.get(url)
        if response and response.status_code == 200:
            try:
                path.write_bytes(response.content)
                logger.debug(f"Successfully downloaded image to {path}")
                return True
            except Exception as e:
                logger.error(f"Failed to write image {url} to {path}: {e}")
        else:
            logger.warning(
                "Failed to fetch image "
                f"{url}. Status: {response.status_code if response else 'N/A'}"
            )

        return False

    def _parse_page(
        self, url: str, content: str
    ) -> Tuple[Optional[ComicRow], List[Tuple[str, Path]]]:
        """Parses the HTML of a single comic page to extract data and image URLs."""
        tree = HTMLParser(content)

        # --- NEW STRATEGY: Prioritize JSON-LD for metadata ---
        comic_date: Optional[date] = None
        canonical_url: str = url

        json_ld_node = tree.css_first('script[type="application/ld+json"]')
        if json_ld_node:
            try:
                json_data = json.loads(json_ld_node.text())
                if "datePublished" in json_data:
                    # Parse YYYY-MM-DD from the ISO timestamp
                    comic_date = date.fromisoformat(
                        json_data["datePublished"].split("T")[0]
                    )
                if "url" in json_data:
                    canonical_url = json_data["url"]
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(
                    f"Could not fully parse JSON-LD for {url}. "
                    f"Will fallback. Error: {e}"
                )

        # --- FALLBACK STRATEGY: Use canonical link and slug ---
        if canonical_url == url:  # If JSON-LD didn't provide a URL
            canonical_url_node = tree.css_first('link[rel="canonical"]')
            if canonical_url_node:
                canonical_url = canonical_url_node.attributes.get("href", url)

        slug = self._extract_slug(canonical_url)

        page_title_node = tree.css_first("title")

        # 2. Find main comic image and its hover text (with fallbacks)
        main_comic_node = tree.css_first("img#cc-comic")  # Original, most specific
        if not main_comic_node:
            # Fallback 1: Look for any image inside the main comic div
            comic_div = tree.css_first("div#comic")
            if comic_div:
                main_comic_node = comic_div.css_first("img")

        if not main_comic_node:
            # Fallback 2: Look in another known container
            comic_body_div = tree.css_first("div#cc-comicbody")
            if comic_body_div:
                main_comic_node = comic_body_div.css_first("img")

        if not main_comic_node:
            logger.warning(
                "Main comic <img> not found for "
                f"{url} using multiple selectors. Skipping."
            )
            return None, []

        main_comic_url = main_comic_node.attributes.get("src", "")
        hover_text = main_comic_node.attributes.get(
            "title", main_comic_node.attributes.get("alt")
        )
        full_main_comic_url = (
            urljoin(self.BASE_URL, main_comic_url) if main_comic_url else ""
        )

        if not comic_date:
            try:
                comic_date = date.fromisoformat(slug)
            except (ValueError, TypeError):
                comic_date = None

        if not comic_date and full_main_comic_url:
            comic_date = self._infer_date_from_image_url(full_main_comic_url)

        if not comic_date:
            logger.warning(
                f"Could not infer a date for {url}; "
                "preserving comic with an undated record."
            )

        # 3. Find 'votey' bonus image and its text
        votey_node = tree.css_first("img#aftercomic")
        votey_text = None
        votey_url = None
        if votey_node:
            votey_url = votey_node.attributes.get("src")
            votey_text = votey_node.attributes.get(
                "title", votey_node.attributes.get("alt")
            )

        # 4. Construct the ComicRow object
        row = ComicRow(
            url=canonical_url,
            slug=slug,
            date=comic_date,
            page_title=page_title_node.text(strip=True) if page_title_node else slug,
            hover_text=hover_text,
            votey_text=votey_text,
            source="smbc",
        )

        # 5. Prepare list of images to be downloaded
        images_to_download = []
        if full_main_comic_url:
            main_image_path = get_image_path(
                self.data_dir, row, full_main_comic_url, is_votey=False
            )
            if main_image_path:
                images_to_download.append((full_main_comic_url, main_image_path))

        if votey_url:
            full_votey_url = urljoin(self.BASE_URL, votey_url)
            votey_image_path = get_image_path(
                self.data_dir, row, full_votey_url, is_votey=True
            )
            if votey_image_path:
                images_to_download.append((full_votey_url, votey_image_path))

        return row, images_to_download

    async def _scrape_one_comic(self, comic_id: int) -> Optional[ComicRow]:
        """Scrapes a single comic page by its ID, handling redirects."""
        url = f"https://www.smbc-comics.com/index.php?db=comics&id={comic_id}"
        response = await self.client.get(url)

        if not response or response.status_code != 200:
            logger.warning(
                f"Request failed for comic ID {comic_id}. URL: {url}. "
                f"Status: {response.status_code if response else 'N/A'}"
            )
            return None

        # The response.url will be the final URL after any redirects
        final_url = str(response.url)

        # Parse the final page content to get the comic row with its canonical
        # date and slug.
        comic_row, images_to_download = self._parse_page(final_url, response.text)

        if not comic_row:
            return None

        # Now that we have a valid comic_row, save the raw HTML for auditability
        html_path = get_html_path(self.data_dir, comic_row)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(response.text, encoding="utf-8")

        # Concurrently download images for this page
        download_tasks = [
            self._download_image(img_url, path) for img_url, path in images_to_download
        ]
        if download_tasks:
            download_results = await asyncio.gather(*download_tasks)
            failed_downloads = sum(not result for result in download_results)
            if failed_downloads:
                logger.warning(
                    f"Comic '{comic_row.slug}' completed with "
                    f"{failed_downloads} failed image download(s)."
                )

        return comic_row

    async def scrape_id_range(self, start_id: int, end_id: int) -> List[ComicRow]:
        """
        Crawls and scrapes all comics in a given ID range, concurrently.
        """
        logger.info(f"Starting SMBC ground-truth scrape from ID {start_id} to {end_id}")

        ids_to_scrape = range(start_id, end_id + 1)
        results: List[ComicRow] = []

        with Progress() as progress:
            task = progress.add_task(
                "[cyan]Scraping smbc-comics.com by ID...", total=len(ids_to_scrape)
            )

            sem = asyncio.Semaphore(8)

            async def bounded(fn, *a, **kw):
                async with sem:
                    return await fn(*a, **kw)

            scrape_tasks = [bounded(self._scrape_one_comic, i) for i in ids_to_scrape]
            # scrape_tasks = [
            #     self._scrape_one_comic(comic_id) for comic_id in ids_to_scrape
            # ]

            for f in asyncio.as_completed(scrape_tasks):
                result = await f
                if result:
                    results.append(result)
                progress.update(task, advance=1)

        logger.info(f"Scrape complete. Found {len(results)} comics in the ID range.")
        return sorted(results, key=lambda r: r.date if r.date else date.min)
