## Tree for smbc_scraper
```
├── cli.py
├── core/
│   ├── files.py
│   ├── http.py
│   └── logging.py
├── export.py
├── models.py
├── sources/
│   ├── ohnorobot.py
│   ├── smbc.py
│   └── smbc_wiki.py
└── __main__.py
```

## File: cli.py
```python
# smbc_scraper/cli.py

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
from pathlib import Path

from loguru import logger
from rich.console import Console

from smbc_scraper.core.http import HttpClient
from smbc_scraper.core.logging import setup_logging
from smbc_scraper.export import save_comics
from smbc_scraper.sources.ohnorobot import OhNoRobotScraper
from smbc_scraper.sources.smbc import SmbcScraper
from smbc_scraper.sources.smbc_wiki import SmbcWikiScraper

console = Console()


def valid_date(s: str) -> date:
    """Argparse type for validating YYYY-MM-DD date strings."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        msg = f"Not a valid date: '{s}'. Expected YYYY-MM-DD."
        raise argparse.ArgumentTypeError(msg)


async def run_smbc(args: argparse.Namespace):
    """Handler for the 'smbc' subcommand."""
    console.print(
        "[bold yellow]Starting Ground-Truth Scrape from smbc-comics.com[/bold yellow]"
    )
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        results = await scraper.scrape_id_range(args.start_id, args.end_id)
        save_comics(results, args.output_dir, "smbc_ground_truth")
    finally:
        await http_client.close()


async def run_ohnorobot(args: argparse.Namespace):
    """Handler for the 'ohnorobot' subcommand."""
    console.print("[bold yellow]Starting Scrape from ohnorobot.com[/bold yellow]")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = OhNoRobotScraper(http_client)
        # The scraper now reads from the output_dir to find source CSVs and generates its own queries.
        results = await scraper.scrape(input_dir=args.output_dir, limit=args.limit)
        save_comics(results, args.output_dir, "ohnorobot")
    finally:
        await http_client.close()


async def run_wiki(args: argparse.Namespace):
    """Handler for the 'wiki' subcommand."""
    console.print("[bold yellow]Starting Scrape from smbc-wiki.com API[/bold yellow]")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcWikiScraper(http_client)
        results = await scraper.scrape_id_range(args.start_id, args.end_id)
        save_comics(results, args.output_dir, "smbc_wiki")
    finally:
        await http_client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape SMBC comics from multiple sources."
    )

    # Global arguments
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out"),
        help="Directory to save output files.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory to save raw HTML and images.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache"),
        help="Directory for HTTP caching.",
    )
    parser.add_argument(
        "--max-rate", type=float, default=2.0, help="Max requests per second."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level.",
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Available commands"
    )

    # Subcommand for smbc.com
    smbc_parser = subparsers.add_parser(
        "smbc", help="Scrape from the main smbc-comics.com site by ID."
    )
    smbc_parser.add_argument(
        "--start-id", type=int, required=True, help="Start comic ID (e.g., 1)."
    )
    smbc_parser.add_argument(
        "--end-id", type=int, required=True, help="End comic ID (e.g., 7500)."
    )
    smbc_parser.set_defaults(func=run_smbc)

    # Subcommand for ohnorobot.com
    onr_parser = subparsers.add_parser("ohnorobot",
                                       help="Scrape from ohnorobot.com by generating queries from existing data.")
    onr_parser.add_argument("--limit", type=int, default=100,
                            help="Number of comics from existing CSVs to use for generating search queries.")
    onr_parser.set_defaults(func=run_ohnorobot)

    # Subcommand for smbc-wiki.com
    wiki_parser = subparsers.add_parser(
        "wiki", help="Scrape transcripts from the smbc-wiki.com API by ID."
    )
    wiki_parser.add_argument(
        "--start-id", type=int, required=True, help="Start comic ID (e.g., 1)."
    )
    wiki_parser.add_argument(
        "--end-id", type=int, required=True, help="End comic ID (e.g., 7500)."
    )
    wiki_parser.set_defaults(func=run_wiki)

    args = parser.parse_args()

    # Setup logging first
    setup_logging(args.log_level)

    # Run the async function associated with the chosen subcommand
    if hasattr(args, "func"):
        try:
            asyncio.run(args.func(args))
            console.print(
                "\n[bold green]All tasks completed successfully![/bold green]"
            )
        except KeyboardInterrupt:
            console.print("\n[bold red]Operation cancelled by user.[/bold red]")
        except Exception as e:
            console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
            # Use logger for the full traceback if in debug mode
            logger.opt(exception=True).debug("Full exception trace:")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```
## File: export.py
```python
# smbc_scraper/export.py

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd
from loguru import logger
from rich.console import Console

from smbc_scraper.models import ComicRow

console = Console()


def save_comics(
    rows: List[ComicRow],
    output_dir: Path,
    source_name: str,
    formats: List[str] = ["csv", "xlsx", "parquet"],
):
    """
    Saves a list of ComicRow objects to specified file formats.
    """
    if not rows:
        logger.warning(
            f"No comic data found for source '{source_name}'. Nothing to export."
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert Pydantic models to a list of dicts for pandas
    data = [row.model_dump(mode="json") for row in rows]
    df = pd.DataFrame(data)

    # Ensure consistent column order
    column_order = [field for field in ComicRow.model_fields.keys()]
    df = df[column_order]

    base_path = output_dir / source_name

    with console.status(
        f"[bold green]Exporting {len(rows)} rows for '{source_name}'..."
    ):
        # Save to CSV
        if "csv" in formats:
            csv_path = base_path.with_suffix(".csv")
            df.to_csv(csv_path, index=False, encoding="utf-8")
            logger.info(f"Saved {len(df)} rows to {csv_path}")

        # Save to XLSX
        if "xlsx" in formats:
            xlsx_path = base_path.with_suffix(".xlsx")
            df.to_excel(xlsx_path, index=False, engine="openpyxl")
            logger.info(f"Saved {len(df)} rows to {xlsx_path}")

        # Save to Parquet (optional)
        if "parquet" in formats:
            try:
                parquet_path = base_path.with_suffix(".parquet")
                df.to_parquet(parquet_path, index=False, engine="pyarrow")
                logger.info(f"Saved {len(df)} rows to {parquet_path}")
            except ImportError:
                logger.warning("`pyarrow` is not installed. Skipping Parquet export.")
            except Exception as e:
                logger.error(f"Failed to export to Parquet: {e}")

    console.print(
        f"[bold green]✓ Export complete for source '{source_name}'.[/bold green]"
    )
```
## File: models.py
```python
# smbc_scraper/models.py

from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class ComicRow(BaseModel):
    """
    Represents a single row of scraped comic data.
    Each source will populate a subset of these fields.
    """

    url: HttpUrl = Field(description="Canonical URL for the comic.")

    slug: str = Field(
        description="Unique identifier, usually the date slug from the URL (e.g., '2025-09-13')."
    )

    comic_text: Optional[str] = Field(
        None,
        description="Transcript of the main comic text, sourced from wiki or ohnorobot.",
    )

    hover_text: Optional[str] = Field(
        None,
        description="The hover text (title/alt attribute) from the main comic image.",
    )

    votey_text: Optional[str] = Field(
        None,
        description="Text from the bonus 'votey' panel, either hover text or transcript.",
    )

    date: Optional[datetime.date] = Field(
        None, description="The publication date of the comic."
    )

    page_title: Optional[str] = Field(
        None, description="The <title> of the comic's HTML page."
    )

    # --- Source-specific metadata ---
    source: str = Field(
        description="The source identifier where this data was scraped from (e.g., 'smbc', 'wiki')."
    )

    # Example of a source-specific field, as mentioned in the spec
    transcript_quality: Optional[str] = Field(
        None, description="Flag for wiki transcripts (e.g., 'auto' or 'manual')."
    )

    class Config:
        # Allows creating instances from ORM objects or dicts
        from_attributes = True
```
## File: __main__.py
```python
import smbc_scraper.cli

if __name__ == "__main__":
    smbc_scraper.cli.main()
```
## File: core\files.py
```python
# smbc_scraper/core/files.py

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from loguru import logger

from smbc_scraper.models import ComicRow


def get_image_path(
    base_dir: Path, comic_row: ComicRow, image_url: str, is_votey: bool = False
) -> Optional[Path]:
    """
    Constructs a structured path for saving a comic image.
    e.g., /base/images/2025/09/13/2025-09-13-main.png
    """
    if not comic_row.date:
        logger.warning(
            f"Cannot determine image path for {comic_row.url} without a date."
        )
        return None

    try:
        parsed_url = urlparse(image_url)
        extension = Path(parsed_url.path).suffix
        if not extension:
            extension = ".png"  # Assume png if no extension found
    except Exception:
        extension = ".png"

    suffix = "votey" if is_votey else "main"
    filename = f"{comic_row.slug}-{suffix}{extension}"

    # Structured path: data/images/YYYY/MM/DD/
    image_path = (
        base_dir
        / "images"
        / str(comic_row.date.year)
        / f"{comic_row.date.month:02d}"
        / f"{comic_row.date.day:02d}"
        / filename
    )

    return image_path


def get_html_path(base_dir: Path, comic_row: ComicRow) -> Path:
    """
    Constructs a structured path for saving raw HTML content.
    e.g., /base/html/2025/09/13/2025-09-13.html
    """
    if not comic_row.date:
        # Fallback for pages where date parsing might fail
        return base_dir / "html" / "misc" / f"{comic_row.slug}.html"

    return (
        base_dir
        / "html"
        / str(comic_row.date.year)
        / f"{comic_row.date.month:02d}"
        / f"{comic_row.date.day:02d}"
        / f"{comic_row.slug}.html"
    )
```
## File: core\http.py
```python
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
```
## File: core\logging.py
```python
# smbc_scraper/core/logging.py

import sys

from loguru import logger


def setup_logging(level: str = "INFO"):
    """Configures Loguru for console output."""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    logger.info(f"Logging configured at level: {level}")
```
## File: sources\ohnorobot.py
```python
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Set
from urllib.parse import urlparse, parse_qs, urlencode

import pandas as pd
from loguru import logger
from rich.progress import Progress
from selectolax.parser import HTMLParser

from smbc_scraper.core.http import HttpClient
from smbc_scraper.models import ComicRow


class OhNoRobotScraper:
    """Scrapes comic transcripts from ohnorobot.com search results."""

    BASE_URL = "https://www.ohnorobot.com/index.php"

    def __init__(self, http_client: HttpClient):
        self.client = http_client

    def _get_id_from_url(self, url: str) -> Optional[str]:
        """Extracts the SMBC comic ID from a URL's query string."""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'id' in query_params:
                return query_params['id'][0]
        except Exception as e:
            logger.warning(f"Could not parse ID from URL '{url}': {e}")
        return None

    def _parse_page(self, content: str) -> List[ComicRow]:
        """Parses a single page of search results from its HTML content."""
        tree = HTMLParser(content)
        results = []

        for blockquote in tree.css("li > blockquote"):
            link_node = blockquote.css_first("a.searchlink")
            if not link_node:
                continue

            url = link_node.attributes.get("href")
            if not url:
                continue

            comic_id = self._get_id_from_url(url)
            if not comic_id:
                logger.debug(f"Skipping result with no parsable comic ID in URL: {url}")
                continue

            for selector in ["div.tinylink", "p"]:
                if node_to_remove := blockquote.css_first(selector):
                    node_to_remove.decompose()

            comic_text = blockquote.text(strip=True, separator="\n")

            results.append(
                ComicRow(
                    url=url,
                    slug=f"smbc-id-{comic_id}",
                    comic_text=comic_text,
                    source="ohnorobot",
                )
            )
        return results

    async def _run_queries(self, queries: List[str]) -> List[ComicRow]:
        """The core worker to perform searches and scrape results."""
        logger.info(f"Running {len(queries)} unique queries on OhNoRobot.")
        all_comics: dict[str, ComicRow] = {}

        with Progress() as progress:
            task = progress.add_task("[cyan]Querying OhNoRobot...", total=len(queries))

            for query in queries:
                page = 0
                seen_on_this_query: Set[str] = set()
                while True:
                    params = {"s": query, "comic": 137, "page": page}
                    full_url = f"{self.BASE_URL}?{urlencode(params)}"
                    logger.debug(f"GET {full_url}")

                    response = await self.client.get(full_url)
                    if not response or response.status_code != 200:
                        logger.warning(
                            f"Failed to fetch page for query '{query}', page {page}. Status: {response.status_code if response else 'N/A'}")
                        break

                    page_results = self._parse_page(response.text)
                    if not page_results:
                        logger.debug(f"No more results for '{query}' on page {page}.")
                        break

                    current_page_urls = {r.url for r in page_results}
                    if current_page_urls.issubset(seen_on_this_query):
                        logger.debug(
                            f"Duplicate results for '{query}' on page {page}, likely end of results. Stopping.")
                        break

                    for comic in page_results:
                        if comic.url not in all_comics:
                            all_comics[comic.url] = comic
                        seen_on_this_query.add(comic.url)
                    page += 1
                progress.update(task, advance=1)

        return sorted(list(all_comics.values()), key=lambda r: int(r.slug.split('-')[-1]))

    async def scrape(self, input_dir: Path, limit: int) -> List[ComicRow]:
        """
        Generates search queries from existing CSV data and scrapes ohnorobot.com.
        """
        logger.info(f"Starting OhNoRobot scrape, generating queries from files in '{input_dir}'")

        smbc_csv_path = input_dir / "smbc_ground_truth.csv"
        wiki_csv_path = input_dir / "smbc_wiki.csv"

        dfs = []
        for path in [smbc_csv_path, wiki_csv_path]:
            if path.exists():
                logger.debug(f"Loading data from {path}")
                try:
                    dfs.append(pd.read_csv(path))
                except Exception as e:
                    logger.error(f"Failed to read {path}: {e}")

        if not dfs:
            logger.error(
                f"No source CSV files found in '{input_dir}'. Cannot generate queries. Run 'smbc' or 'wiki' scrapers first.")
            return []

        combined_df = pd.concat(dfs).drop_duplicates(subset=['url']).sort_values('url').reset_index(drop=True)

        queries = set()
        rows_to_process = combined_df.head(limit)

        for _, row in rows_to_process.iterrows():
            title = str(row.get('page_title', ''))
            title = re.sub(r'Saturday Morning Breakfast Cereal -?', '', title, flags=re.IGNORECASE).strip()
            title = re.sub(r'[^a-zA-Z0-9\s]', '', title).strip()
            if title and (query := " ".join(title.split()[:3])):
                queries.add(query)

        if not queries:
            logger.warning("Could not generate any search queries from the input files.")
            return []

        logger.info(f"Generated {len(queries)} unique search queries from the first {len(rows_to_process)} comics.")

        return await self._run_queries(list(queries))
```
## File: sources\smbc.py
```python
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

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

    def __init__(self, http_client: HttpClient, data_dir: str):
        self.client = http_client
        self.data_dir = Path(data_dir)

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
                f"Failed to fetch image {url}. Status: {response.status_code if response else 'N/A'}"
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
                    f"Could not fully parse JSON-LD for {url}. Will fallback. Error: {e}"
                )

        # --- FALLBACK STRATEGY: Use canonical link and slug ---
        if canonical_url == url:  # If JSON-LD didn't provide a URL
            canonical_url_node = tree.css_first('link[rel="canonical"]')
            if canonical_url_node:
                canonical_url = canonical_url_node.attributes.get("href", url)

        slug = Path(canonical_url).stem

        if not comic_date:  # If JSON-LD didn't provide a date
            try:
                comic_date = date.fromisoformat(slug)
            except (ValueError, TypeError):
                logger.warning(
                    f"Could not parse date from slug '{slug}' or JSON-LD for URL {url}. Skipping."
                )
                return None, []

        if not comic_date:  # Final check, should be unreachable
            logger.error(f"Failed to determine a date for {url}. Skipping comic.")
            return None, []

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
                f"Main comic <img> not found for {url} using multiple selectors. Skipping."
            )
            return None, []

        main_comic_url = main_comic_node.attributes.get("src", "")
        hover_text = main_comic_node.attributes.get(
            "title", main_comic_node.attributes.get("alt")
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
        if main_comic_url:
            # FIX: Ensure main comic URL is absolute, handling both relative and absolute paths.
            if main_comic_url.startswith("http"):
                full_main_comic_url = main_comic_url
            else:
                full_main_comic_url = f"{self.BASE_URL}{main_comic_url}"

            main_image_path = get_image_path(
                self.data_dir, row, full_main_comic_url, is_votey=False
            )
            if main_image_path:
                images_to_download.append((full_main_comic_url, main_image_path))

        if votey_url:
            # Votey urls are sometimes absolute, sometimes relative
            if votey_url.startswith("http"):
                full_votey_url = votey_url
            else:
                full_votey_url = f"{self.BASE_URL}{votey_url}"
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
                f"Request failed for comic ID {comic_id}. URL: {url}. Status: {response.status_code if response else 'N/A'}"
            )
            return None

        # The response.url will be the final URL after any redirects
        final_url = str(response.url)

        # Parse the final page content to get the comic_row with its canonical date and slug
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
        await asyncio.gather(*download_tasks)

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
                "[cyan]Scraping SMBC.com by ID...", total=len(ids_to_scrape)
            )

            scrape_tasks = [
                self._scrape_one_comic(comic_id) for comic_id in ids_to_scrape
            ]

            for f in asyncio.as_completed(scrape_tasks):
                result = await f
                if result:
                    results.append(result)
                progress.update(task, advance=1)

        logger.info(f"Scrape complete. Found {len(results)} comics in the ID range.")
        return sorted(results, key=lambda r: r.date if r.date else date.min)
```
## File: sources\smbc_wiki.py
```python
from __future__ import annotations

import asyncio
import json
import re
from typing import List, Optional
from urllib.parse import urlencode

from loguru import logger
from rich.progress import Progress

from smbc_scraper.core.http import HttpClient
from smbc_scraper.models import ComicRow


class SmbcWikiScraper:
    """Scrapes comic transcripts from the smbc-wiki.com MediaWiki API by ID."""

    API_URL = "https://www.smbc-wiki.com/api.php"

    def __init__(self, http_client: HttpClient):
        self.client = http_client

    def _extract_section(self, wikitext: str, section_name: str) -> Optional[str]:
        """Extracts text from a specific wikitext section (e.g., ==Transcript==)."""
        logger.trace(f"Attempting to extract section: '{section_name}'")
        # This pattern looks for a section header and captures content until the next header of the same or higher level.
        pattern = re.compile(
            rf"==\s*{section_name}\s*==\n(.*?)(?=\n==[^=]|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(wikitext)
        if match:
            # Clean up wikitext markup (e.g., {{...}}, ''', '''')
            text = match.group(1).strip()
            text = re.sub(r"\{\{.*?\}\}", "", text)
            text = re.sub(r"'''(.*?)'''", r"\1", text)
            text = re.sub(r"''(.*?)''", r"\1", text)
            logger.trace(f"Extracted section '{section_name}' successfully.")
            return text

        logger.trace(f"Section '{section_name}' not found in wikitext.")
        return None

    def _extract_smbc_url(self, wikitext: str) -> Optional[str]:
        """Finds or constructs the original smbc-comics.com URL from the wikitext."""
        # Defines patterns to find either modern (/comic/slug) or legacy (index.php?...) URLs.
        # It tries a more specific pattern (inside a template) first.
        explicit_url_patterns = [
            # 1. Look for explicit URL in a comic template: {{Comic|...|url=...}}
            # It captures either URL format.
            r"\|\s*url\s*=\s*(https?://www\.smbc-comics\.com/(?:comic/[\w-]+|index\.php\?[\w=&;-]+))",
            # 2. Fallback: Look for any standalone SMBC comic URL.
            r"(https?://www\.smbc-comics\.com/(?:comic/[\w-]+|index\.php\?[\w=&;-]+))",
        ]

        for pattern in explicit_url_patterns:
            match = re.search(pattern, wikitext)
            if match:
                url = match.group(1).strip()
                logger.trace(
                    f"Found explicit SMBC URL '{url}' using pattern: '{pattern}'"
                )
                return url

        # 3. Fallback: If no explicit URL, try to construct it from the |title= field in the {{comic}} template.
        # This is common in older wiki pages like the one you found.
        title_slug_pattern = r"\{\{comic.*?\|\s*title\s*=\s*([\w-]+)"
        match = re.search(title_slug_pattern, wikitext, re.DOTALL | re.IGNORECASE)
        if match:
            slug = match.group(1).strip()
            # Ensure the extracted slug looks like a date or a valid slug, not just a number (which might be the comic ID)
            if re.match(r"^\d{4}-\d{2}-\d{2}$", slug) or not slug.isdigit():
                url = f"https://www.smbc-comics.com/comic/{slug}"
                logger.info(
                    f"Constructed SMBC URL '{url}' from wiki template title field."
                )
                return url

        logger.trace("Could not find or construct an SMBC URL from the wikitext.")
        return None

    async def _fetch_and_parse_page(
        self, page_title_or_id: str, original_id: int, redirect_depth: int = 0
    ) -> Optional[ComicRow]:
        """
        Fetches a wiki page by title/ID, handles redirects, and parses the content.
        """
        if redirect_depth > 3:
            logger.error(
                f"Redirect limit exceeded for initial comic ID '{original_id}'. Aborting."
            )
            return None

        params = {
            "action": "parse",
            "page": page_title_or_id,
            "prop": "wikitext",
            "format": "json",
        }
        full_url = f"{self.API_URL}?{urlencode(params)}"
        logger.debug(f"GET {full_url}")

        response = await self.client.get(full_url)
        if not response or response.status_code != 200:
            return None

        try:
            logger.trace(
                f"Response body for page '{page_title_or_id}':\n{response.text}"
            )
            data = response.json()
            if "error" in data and data["error"]["code"] == "missingtitle":
                logger.debug(f"No wiki page found for title/ID '{page_title_or_id}'")
                return None

            wikitext = data["parse"]["wikitext"]["*"]

            # Handle redirects
            redirect_match = re.match(
                r"#REDIRECT\s*\[\[(.*?)\]\]", wikitext, re.IGNORECASE
            )
            if redirect_match:
                new_page_title = redirect_match.group(1).strip()
                logger.info(
                    f"ID {original_id} ('{page_title_or_id}') redirects to '{new_page_title}'. Following."
                )
                return await self._fetch_and_parse_page(
                    new_page_title, original_id, redirect_depth + 1
                )

            page_title = data["parse"]["title"]
            url = self._extract_smbc_url(wikitext)
            if not url:
                logger.warning(
                    f"Could not find SMBC URL in wiki page for ID: '{original_id}' (final page: '{page_title}')"
                )
                return None

            # Generate slug based on URL format
            if "/comic/" in url:
                slug = url.split("/")[-1]
            else:
                slug = str(
                    original_id
                )  # Use original ID for a stable slug on legacy URLs

            comic_text = self._extract_section(wikitext, "Transcript")
            votey_text = self._extract_section(wikitext, "Votey")

            return ComicRow(
                url=url,
                slug=slug,
                page_title=page_title,
                comic_text=comic_text,
                votey_text=votey_text,
                source="smbc-wiki",
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            logger.error(
                f"Failed to parse wiki JSON for page '{page_title_or_id}' (from ID {original_id}). Error: {e}"
            )
            logger.error("--- Raw Response Text that caused the error ---")
            logger.error(response.text)
            logger.error("--- End Raw Response Text ---")
            return None

    async def scrape_id_range(self, start_id: int, end_id: int) -> List[ComicRow]:
        """Scrapes all wiki pages within a given comic ID range."""
        logger.info(f"Starting SMBC-Wiki scrape from ID {start_id} to {end_id}")

        ids_to_scrape = range(start_id, end_id + 1)
        results: List[ComicRow] = []

        with Progress() as progress:
            task = progress.add_task(
                "[cyan]Scraping SMBC-Wiki by ID...", total=len(ids_to_scrape)
            )

            scrape_tasks = [
                self._fetch_and_parse_page(str(comic_id), original_id=comic_id)
                for comic_id in ids_to_scrape
            ]

            for f in asyncio.as_completed(scrape_tasks):
                result = await f
                if result:
                    results.append(result)
                progress.update(task, advance=1)

        logger.info(f"SMBC-Wiki scrape complete. Parsed {len(results)} pages.")
        return sorted(results, key=lambda r: r.slug)
```
