from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Set, Optional
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

