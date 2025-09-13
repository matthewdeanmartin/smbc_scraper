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
    data = [row.model_dump() for row in rows]
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
