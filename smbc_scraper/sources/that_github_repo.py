from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional

import yaml
from loguru import logger

from smbc_scraper.export import save_comics
from smbc_scraper.models import ComicRow


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE_IN_URL_RE = re.compile(r"(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>[0-2][0-9]|3[01])")


def _extract_front_matter(markdown_text: str) -> tuple[dict, str]:
    """Return (front_matter_dict, body_markdown).

    If no front matter is present, returns ({}, original_text).
    """
    match = FRONT_MATTER_RE.match(markdown_text)
    if not match:
        return {}, markdown_text

    front_matter_raw = match.group(1)
    try:
        fm: dict = yaml.safe_load(front_matter_raw) or {}
        if not isinstance(fm, dict):
            logger.warning("Front matter parsed to non-dict; ignoring.")
            fm = {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to parse front matter YAML: {exc}")
        fm = {}

    body = markdown_text[match.end() :]
    return fm, body


def _infer_date_from_front_matter(fm: dict) -> Optional["datetime.date"]:
    """Try to infer a date from common SMBC image URLs embedded in front matter.

    Looks for YYYYMMDD in the 'image' or 'extra_image' fields.
    """
    import datetime as _dt

    for key in ("image", "extra_image"):
        val = fm.get(key)
        if isinstance(val, str):
            m = DATE_IN_URL_RE.search(val)
            if m:
                try:
                    return _dt.date(
                        int(m.group("year")), int(m.group("month")), int(m.group("day"))
                    )
                except ValueError:
                    pass
    return None


def _slug_from_path(path: Path) -> str:
    """Derive a slug from the filename stem.

    E.g., `2021-06-12-titan.md` -> `2021-06-12-titan`.
    """
    return path.stem


def _canonical_url(slug: str) -> str:
    """Construct a canonical SMBC URL from a slug.

    This assumes standard SMBC paths: https://www.smbc-comics.com/comic/<slug>
    """
    return f"https://www.smbc-comics.com/comic/{slug}"


def parse_markdown_file(path: Path) -> ComicRow:
    """Parse a single markdown file into a ComicRow.

    Expected format: YAML front matter delimited by '---' followed by markdown body.
    Front matter keys of interest:
      - title -> page_title
      - hovertext -> hover_text
      - image/extra_image (used to infer date)

    Any missing fields are left as None where optional. Required fields (url, slug, source)
    are synthesized from the filename and known SMBC URL pattern.
    """
    text = path.read_text(encoding="utf-8")
    fm, body = _extract_front_matter(text)

    slug = _slug_from_path(path)
    url = _canonical_url(slug)

    hover_text = fm.get("hovertext") if isinstance(fm.get("hovertext"), str) else None
    page_title = fm.get("title") if isinstance(fm.get("title"), str) else None

    date = _infer_date_from_front_matter(fm)

    # Use the remaining markdown body as the comic transcript text.
    comic_text = body.strip() or None

    row = ComicRow(
        url=url,
        slug=slug,
        comic_text=comic_text,
        hover_text=hover_text,
        votey_text=None,
        date=date,
        page_title=page_title,
        source="local_md",
        transcript_quality=None,
    )
    return row


def iter_markdown_files(root: Path) -> Iterable[Path]:
    """Yield all markdown files under root (recursively)."""
    yield from root.rglob("*.md")
    yield from root.rglob("*.markdown")


def load_rows_from_folder(folder: Path) -> List[ComicRow]:
    """Parse all markdown files in *folder* into ComicRow objects."""
    files = list(iter_markdown_files(folder))
    if not files:
        logger.warning(f"No markdown files found under {folder}")
        return []

    rows: List[ComicRow] = []
    for fp in files:
        try:
            rows.append(parse_markdown_file(fp))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(f"Failed to parse {fp}: {exc}")
    return rows


def run_export(input_dir: Path, out_dir: Path = Path("./out")) -> None:
    """High-level entry point to parse *input_dir* and export CSV/XLSX to *out_dir*.

    This writes:
      - ./out/local_md.csv
      - ./out/local_md.xlsx
    (and parquet if your environment supports pyarrow)
    """
    rows = load_rows_from_folder(input_dir)
    if not rows:
        logger.warning("No rows parsed; nothing to export.")
        return

    save_comics(rows=rows, output_dir=out_dir, source_name="local_md", formats=["csv", "xlsx"])  # parquet optional


# Example usage (programmatic):
# from pathlib import Path
# from smbc_scraper.local_md_ingest import run_export
if __name__ == '__main__':
    run_export(Path("C:\\github\\smbc\\_comics"))
