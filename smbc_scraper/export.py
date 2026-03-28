# smbc_scraper/export.py

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import List

import pandas as pd
from loguru import logger
from rich.console import Console

from smbc_scraper.models import ComicRow

console = Console()


def _normalize_optional_csv_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_comics(csv_path: Path) -> list[ComicRow]:
    """Load ComicRow items from an existing CSV export."""
    if not csv_path.exists():
        return []

    rows: list[ComicRow] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            normalized = {
                field_name: _normalize_optional_csv_value(raw_row.get(field_name))
                for field_name in ComicRow.model_fields
            }
            if not normalized.get("url") or not normalized.get("slug"):
                logger.warning(f"Skipping malformed comic row in {csv_path}: {raw_row}")
                continue
            rows.append(ComicRow.model_validate(normalized))
    return rows


def sort_comics(rows: list[ComicRow]) -> list[ComicRow]:
    """Return comics in a stable chronological order."""
    return sorted(rows, key=lambda row: (row.date or date.min, row.slug, str(row.url)))


def merge_comics(
    existing_rows: list[ComicRow], new_rows: list[ComicRow]
) -> list[ComicRow]:
    """Merge two comic collections, preferring newer rows on URL collisions."""
    merged_by_url = {str(row.url): row for row in existing_rows}
    for row in new_rows:
        merged_by_url[str(row.url)] = row
    return sort_comics(list(merged_by_url.values()))


def save_comics(
    rows: List[ComicRow],
    output_dir: Path,
    source_name: str,
    formats: List[str] | None = None,
):
    """
    Saves a list of ComicRow objects to specified file formats.
    """
    if not formats:
        formats = ["csv", "xlsx", "parquet"]

    if not rows:
        logger.warning(
            f"No comic data found for source '{source_name}'. Nothing to export."
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert Pydantic models to a list of dicts for pandas
    # data = [row.model_dump(mode="json") for row in rows]
    data = [row.model_dump() for row in sort_comics(rows)]
    df = pd.DataFrame(data)

    # Ensure consistent column order
    column_order = list(ComicRow.model_fields.keys())
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
