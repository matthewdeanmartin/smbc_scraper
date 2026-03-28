from __future__ import annotations

from datetime import date
from pathlib import Path

from smbc_scraper.export import load_comics, merge_comics
from smbc_scraper.models import ComicRow


def build_comic_row(slug: str, when: date, hover_text: str = "hover") -> ComicRow:
    return ComicRow(
        url=f"https://www.smbc-comics.com/comic/{slug}",
        slug=slug,
        date=when,
        hover_text=hover_text,
        page_title=slug.title(),
        source="smbc",
    )


def test_load_comics_reads_existing_csv(tmp_path: Path):
    csv_path = tmp_path / "smbc_ground_truth.csv"
    csv_path.write_text(
        "url,slug,comic_text,hover_text,votey_text,date,page_title,source,transcript_quality\n"
        "https://www.smbc-comics.com/comic/critical,critical,,hover,,2024-09-01,Critical,smbc,\n",
        encoding="utf-8",
    )

    rows = load_comics(csv_path)

    assert len(rows) == 1
    assert rows[0].slug == "critical"
    assert rows[0].date == date(2024, 9, 1)
    assert rows[0].hover_text == "hover"


def test_merge_comics_prefers_new_rows_and_sorts():
    existing_rows = [
        build_comic_row("beta", date(2024, 9, 2), hover_text="old beta"),
        build_comic_row("alpha", date(2024, 9, 1), hover_text="old alpha"),
    ]
    new_rows = [
        build_comic_row("beta", date(2024, 9, 2), hover_text="new beta"),
        build_comic_row("gamma", date(2024, 9, 3), hover_text="new gamma"),
    ]

    merged_rows = merge_comics(existing_rows, new_rows)

    assert [row.slug for row in merged_rows] == ["alpha", "beta", "gamma"]
    beta_row = next(row for row in merged_rows if row.slug == "beta")
    assert beta_row.hover_text == "new beta"
