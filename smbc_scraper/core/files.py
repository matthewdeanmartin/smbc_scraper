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
