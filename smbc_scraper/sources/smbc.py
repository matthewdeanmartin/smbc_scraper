from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from loguru import logger
from rich.progress import Progress
from selectolax.parser import HTMLParser

from smbc_scraper.core.files import get_html_path, get_image_path
from smbc_scraper.core.http import HttpGetClient
from smbc_scraper.export import load_comics
from smbc_scraper.models import ComicRow

DEFAULT_INCREMENTAL_STATE_FILENAME = "smbc_ground_truth_state.json"


@dataclass(frozen=True)
class IncrementalScrapeState:
    last_scraped_id: int


def load_incremental_state(state_path: Path) -> Optional[IncrementalScrapeState]:
    """Load incremental scrape state from disk if present."""
    if not state_path.exists():
        return None

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    last_scraped_id = payload.get("last_scraped_id")
    if not isinstance(last_scraped_id, int) or last_scraped_id < 1:
        msg = (
            f"Invalid incremental state in {state_path}: "
            f"expected positive integer last_scraped_id."
        )
        raise ValueError(msg)

    return IncrementalScrapeState(last_scraped_id=last_scraped_id)


def save_incremental_state(state_path: Path, state: IncrementalScrapeState) -> None:
    """Persist the last successful legacy comic ID for future incremental runs."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"last_scraped_id": state.last_scraped_id}, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_incremental_start_id(
    state_path: Path,
    start_id: Optional[int] = None,
) -> tuple[int, Optional[IncrementalScrapeState]]:
    """Resolve the next start ID from either an explicit override or saved state."""
    state = load_incremental_state(state_path)
    if start_id is not None:
        return start_id, state
    if state is None:
        msg = "No incremental state file found."
        raise ValueError(msg)
    return state.last_scraped_id + 1, state


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

    def __init__(self, http_client: HttpGetClient, data_dir: str):
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

    def _parse_page(  # noqa: C901
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
                canonical_url = canonical_url_node.attributes.get("href") or url

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

    async def _get_row_for_legacy_id(self, comic_id: int) -> Optional[ComicRow]:
        """Fetch and parse a legacy ID without writing files or downloading images."""
        url = f"https://www.smbc-comics.com/index.php?db=comics&id={comic_id}"
        response = await self.client.get(url)

        if not response or response.status_code != 200:
            logger.warning(
                f"Probe request failed for comic ID {comic_id}. "
                f"Status: {response.status_code if response else 'N/A'}"
            )
            return None

        comic_row, _ = self._parse_page(str(response.url), response.text)
        return comic_row

    async def get_latest_comic_slug(self) -> str:
        """Fetch the latest comic slug from the homepage."""
        response = await self.client.get(self.BASE_URL)
        if not response or response.status_code != 200:
            msg = "Could not fetch the SMBC homepage to discover the latest comic."
            raise RuntimeError(msg)

        comic_row, _ = self._parse_page(str(response.url), response.text)
        if not comic_row:
            msg = "Could not parse the latest SMBC comic from the homepage."
            raise RuntimeError(msg)

        return comic_row.slug

    async def discover_latest_legacy_id(
        self, initial_probe_id: int = 8192, max_probe_id: int = 65536
    ) -> int:
        """Find the smallest legacy ID that resolves to the latest comic slug."""
        if initial_probe_id < 1:
            raise ValueError("initial_probe_id must be >= 1")
        if max_probe_id < initial_probe_id:
            raise ValueError("max_probe_id must be >= initial_probe_id")

        latest_slug = await self.get_latest_comic_slug()
        probe_cache: dict[int, Optional[str]] = {}

        async def get_slug(probe_id: int) -> Optional[str]:
            if probe_id not in probe_cache:
                row = await self._get_row_for_legacy_id(probe_id)
                probe_cache[probe_id] = row.slug if row else None
            return probe_cache[probe_id]

        upper = initial_probe_id
        while True:
            upper_slug = await get_slug(upper)
            if upper_slug == latest_slug:
                break
            upper *= 2
            if upper > max_probe_id:
                msg = (
                    "Could not discover the latest legacy SMBC ID within the "
                    f"configured probe ceiling ({max_probe_id})."
                )
                raise RuntimeError(msg)

        lower = 1
        while lower < upper:
            middle = (lower + upper) // 2
            middle_slug = await get_slug(middle)
            if middle_slug == latest_slug:
                upper = middle
            else:
                lower = middle + 1

        logger.info(f"Discovered latest SMBC legacy ID: {lower}")
        return lower

    async def scrape_full_archive(
        self, start_id: int = 1
    ) -> tuple[List[ComicRow], int]:
        """Scrape the full SMBC archive through the latest discovered legacy ID."""
        if start_id < 1:
            raise ValueError("start_id must be >= 1")

        latest_legacy_id = await self.discover_latest_legacy_id()
        rows = await self.scrape_id_range(start_id, latest_legacy_id)
        return rows, latest_legacy_id

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

    async def scrape_incremental(
        self,
        start_id: int,
        stop_after_missing: int = 20,
        max_new_comics: Optional[int] = None,
    ) -> tuple[List[ComicRow], Optional[int]]:
        """Scrape forward from a starting ID until a bounded streak of misses."""
        if start_id < 1:
            raise ValueError("start_id must be >= 1")
        if stop_after_missing < 1:
            raise ValueError("stop_after_missing must be >= 1")
        if max_new_comics is not None and max_new_comics < 1:
            raise ValueError("max_new_comics must be >= 1 when provided")

        logger.info(
            "Starting incremental SMBC scrape "
            f"from ID {start_id} with stop_after_missing={stop_after_missing}"
        )
        results: List[ComicRow] = []
        consecutive_misses = 0
        current_id = start_id
        last_successful_id: Optional[int] = None

        while consecutive_misses < stop_after_missing:
            comic_row = await self._scrape_one_comic(current_id)
            if comic_row is None:
                consecutive_misses += 1
            else:
                results.append(comic_row)
                last_successful_id = current_id
                consecutive_misses = 0
                if max_new_comics is not None and len(results) >= max_new_comics:
                    break
            current_id += 1

        logger.info(
            "Incremental SMBC scrape complete. "
            f"Found {len(results)} new comic(s); "
            f"last_successful_id={last_successful_id!r}."
        )
        return (
            sorted(results, key=lambda row: row.date if row.date else date.min),
            last_successful_id,
        )

    async def _backfill_one_row(self, row: ComicRow, overwrite: bool) -> int:
        response = await self.client.get(str(row.url))
        if not response or response.status_code != 200:
            logger.warning(
                "Request failed during image backfill for "
                f"{row.url}. Status: {response.status_code if response else 'N/A'}"
            )
            return 0

        parsed_row, images_to_download = self._parse_page(
            str(response.url), response.text
        )
        if not parsed_row:
            logger.warning(
                f"Could not parse comic page during image backfill: {row.url}"
            )
            return 0

        if not overwrite:
            images_to_download = [
                (image_url, image_path)
                for image_url, image_path in images_to_download
                if not image_path.exists()
            ]

        if not images_to_download:
            return 0

        download_results = await asyncio.gather(
            *[
                self._download_image(image_url, image_path)
                for image_url, image_path in images_to_download
            ]
        )
        return sum(1 for result in download_results if result)

    async def backfill_images(
        self,
        source_csv_path: Path,
        limit: Optional[int] = None,
        overwrite: bool = False,
        concurrency: int = 2,
    ) -> int:
        """Download missing comic images from existing SMBC metadata exports."""
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")

        source_rows = load_comics(source_csv_path)
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be >= 1 when provided")
            source_rows = source_rows[:limit]

        if not source_rows:
            logger.warning(
                f"No SMBC rows available for image backfill in {source_csv_path}"
            )
            return 0

        logger.info(
            "Starting SMBC image backfill for "
            f"{len(source_rows)} comic(s). overwrite={overwrite}"
        )
        downloaded_images = 0
        sem = asyncio.Semaphore(concurrency)

        async def backfill_one(row: ComicRow) -> int:
            async with sem:
                return await self._backfill_one_row(row, overwrite=overwrite)

        with Progress() as progress:
            task = progress.add_task(
                "[cyan]Backfilling SMBC images...", total=len(source_rows)
            )
            backfill_tasks = [backfill_one(row) for row in source_rows]
            for future in asyncio.as_completed(backfill_tasks):
                downloaded_images += await future
                progress.update(task, advance=1)

        logger.info(
            f"SMBC image backfill complete. Downloaded {downloaded_images} image(s)."
        )
        return downloaded_images
