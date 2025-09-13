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

            sem = asyncio.Semaphore(8)

            async def bounded(fn, *a, **kw):
                async with sem:
                    return await fn(*a, **kw)

            scrape_tasks = [bounded(self._fetch_and_parse_page, original_id=comic_id) for comic_id in ids_to_scrape]
            # scrape_tasks = [
            #     self._fetch_and_parse_page(str(comic_id), original_id=comic_id)
            #     for comic_id in ids_to_scrape
            # ]

            for f in asyncio.as_completed(scrape_tasks):
                result = await f
                if result:
                    results.append(result)
                progress.update(task, advance=1)

        logger.info(f"SMBC-Wiki scrape complete. Parsed {len(results)} pages.")
        return sorted(results, key=lambda r: r.slug)
