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

    def _extract_legacy_id(self, url: str) -> Optional[int]:
        """
        Extract a legacy ID from index.php?id=<id>
        or index.php?db=comics&id=<id> URLs.
        """
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        if comic_ids := query_params.get("id"):
            try:
                return int(comic_ids[0])
            except ValueError:
                pass

        # Try to see if slug is an ID
        slug = self._extract_slug(url)
        try:
            return int(slug)
        except ValueError:
            return None

    def _extract_slug(self, url: str) -> str:
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

    async def rebuild_id_index_from_local_files(
        self, source_csv_path: Path, max_id: Optional[int] = None
    ) -> List[ComicRow]:
        """
        Reconstruct the legacy ID → slug mapping and backfill legacy_id in the CSV.

        The saved HTML pages do not embed the legacy ID, so we walk the full ID
        range by requesting each index.php?db=comics&id=N URL.  These requests
        will be served from the HTTP cache (populated by the original full scrape)
        so they are fast and require no network access for already-scraped IDs.
        """
        existing_rows = load_comics(source_csv_path)
        # Use mutable dicts so we can update legacy_id in place.
        row_map: dict[str, dict] = {
            row.slug: row.model_dump() for row in existing_rows
        }

        if not row_map:
            logger.warning("No existing rows found in CSV; nothing to rebuild.")
            return []

        if not max_id:
            max_id = await self.discover_latest_legacy_id()

        # Only probe IDs for rows that still lack a legacy_id.
        slugs_missing_id = {
            slug for slug, d in row_map.items() if d.get("legacy_id") is None
        }
        if not slugs_missing_id:
            logger.info("All rows already have a legacy_id; nothing to rebuild.")
            return existing_rows

        logger.info(
            f"Probing IDs 1–{max_id} to backfill legacy_id "
            f"for {len(slugs_missing_id)} rows (HTTP cache will be used)..."
        )

        updated_count = 0
        sem = asyncio.Semaphore(16)

        async def probe(i: int) -> Tuple[int, Optional[str]]:
            async with sem:
                row = await self._get_row_for_legacy_id(i)
                return i, (row.slug if row else None)

        with Progress() as progress:
            task = progress.add_task(
                "[cyan]Rebuilding ID index...", total=max_id
            )
            probe_futures = [probe(i) for i in range(1, max_id + 1)]
            for f in asyncio.as_completed(probe_futures):
                comic_id, slug = await f
                if slug and slug in slugs_missing_id:
                    row_map[slug]["legacy_id"] = comic_id
                    slugs_missing_id.discard(slug)
                    updated_count += 1
                progress.update(task, advance=1)

        logger.info(f"Rebuilt legacy_id for {updated_count} rows.")
        if slugs_missing_id:
            logger.warning(
                f"{len(slugs_missing_id)} rows still have no legacy_id "
                "(not found in the probed ID range)."
            )
        return [ComicRow.model_validate(d) for d in row_map.values()]

    async def _resolve_truly_missing_ids(
        self, candidate_ids: List[int], existing_slugs: set[str]
    ) -> List[int]:
        """Resolve ID→slug mapping to find IDs not yet in the CSV."""
        truly_missing: List[int] = []
        sem = asyncio.Semaphore(4)

        async def probe_id(i: int) -> Tuple[int, Optional[str], bool]:
            async with sem:
                row = await self._get_row_for_legacy_id(i)
                if row is None:
                    return i, None, False
                return i, row.slug, True

        probe_failed = 0
        with Progress() as progress:
            probe_task = progress.add_task(
                "[cyan]Resolving ID→slug mapping...", total=len(candidate_ids)
            )
            probe_futures = [probe_id(i) for i in candidate_ids]
            for f in asyncio.as_completed(probe_futures):
                comic_id, slug, ok = await f
                if not ok:
                    probe_failed += 1
                elif slug not in existing_slugs:
                    truly_missing.append(comic_id)
                progress.update(probe_task, advance=1)

        if probe_failed:
            logger.warning(
                f"{probe_failed} ID probes failed (rate-limited or network error); "
                "those IDs were skipped. Re-run to retry them."
            )
        return truly_missing

    async def scrape_missing_ids(
        self, source_csv_path: Path, max_id: Optional[int] = None
    ) -> List[ComicRow]:
        """
        Identify missing IDs in the given range and scrape them.

        Uses slugs (not legacy_id) as the primary existence check so that
        CSVs produced before the legacy_id field was introduced are handled
        correctly.  Legacy IDs are used as a fast-path skip when available.
        """
        if not source_csv_path.exists():
            logger.warning(f"Source CSV not found: {source_csv_path}")
            return []

        existing_rows = load_comics(source_csv_path)
        existing_slugs: set[str] = {row.slug for row in existing_rows}
        existing_ids: set[int] = {
            row.legacy_id for row in existing_rows if row.legacy_id is not None
        }

        if not max_id:
            max_id = await self.discover_latest_legacy_id()

        candidate_ids = [i for i in range(1, max_id + 1) if i not in existing_ids]
        if not candidate_ids:
            logger.info("No missing IDs found.")
            return []

        logger.info(
            f"Checking {len(candidate_ids)} IDs not covered by legacy_id index "
            f"(total max_id={max_id}, already indexed={len(existing_ids)})..."
        )

        truly_missing = await self._resolve_truly_missing_ids(
            candidate_ids, existing_slugs
        )

        if not truly_missing:
            logger.info("No missing IDs found after slug resolution.")
            return []

        logger.info(f"Found {len(truly_missing)} truly missing IDs. Scraping...")
        new_rows: List[ComicRow] = []
        sem = asyncio.Semaphore(4)
        with Progress() as progress:
            scrape_task = progress.add_task(
                "[cyan]Scraping missing SMBC IDs...", total=len(truly_missing)
            )

            async def bounded_scrape(i: int) -> Optional[ComicRow]:
                async with sem:
                    return await self._scrape_one_comic(i)

            scrape_futures = [bounded_scrape(i) for i in truly_missing]
            for f in asyncio.as_completed(scrape_futures):
                result = await f
                if result:
                    new_rows.append(result)
                progress.update(scrape_task, advance=1)

        return new_rows

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
        self, url: str, content: str, legacy_id: Optional[int] = None
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
            legacy_id=legacy_id,
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
        comic_row, images_to_download = self._parse_page(
            final_url, response.text, legacy_id=comic_id
        )

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

        comic_row, _ = self._parse_page(
            str(response.url), response.text, legacy_id=comic_id
        )
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
        self, start_id: int = 1, limit: Optional[int] = None
    ) -> tuple[List[ComicRow], int]:
        """Scrape the full SMBC archive through the latest discovered legacy ID."""
        if start_id < 1:
            raise ValueError("start_id must be >= 1")

        latest_legacy_id = await self.discover_latest_legacy_id()
        end_id = (
            min(start_id + limit - 1, latest_legacy_id)
            if limit
            else latest_legacy_id
        )
        rows = await self.scrape_id_range(start_id, end_id)
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
            str(response.url), response.text, legacy_id=row.legacy_id
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
