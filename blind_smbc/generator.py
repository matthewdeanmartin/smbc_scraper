# blind_smbc/generator.py
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# Configuration
DATA_PATH_GOLD = Path("../gold_data/smbc_ground_truth.csv")
DATA_PATH_OUT = Path("../out/smbc_ground_truth.csv")
VARIANTS_PATH = Path("../out/smbc_vision_variants.csv")
STAGEPLAY_PATH = Path("../out/smbc_vision_stageplay.csv")
OUTPUT_DIR = Path("./dist")
TEMPLATES_DIR = Path("./templates")
STATIC_DIR = Path("./static")
DIAGNOSTICS_DIR = "text-diagnostics"


def setup_directories() -> None:
    """Ensure output directories exist and copy static assets."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "comics").mkdir(exist_ok=True)
    (OUTPUT_DIR / DIAGNOSTICS_DIR).mkdir(exist_ok=True)
    (OUTPUT_DIR / "static").mkdir(exist_ok=True)
    shutil.copy(STATIC_DIR / "style.css", OUTPUT_DIR / "static" / "style.css")


def _ensure_text_column(df: pd.DataFrame, column: str) -> None:
    if column in df.columns:
        df[column] = df[column].fillna("").astype(str)
    else:
        df[column] = ""


def _load_best_main_rows(csv_path: Path, text_columns: list[str]) -> pd.DataFrame:
    rows = pd.read_csv(csv_path)
    if "image_kind" in rows.columns:
        rows = rows[rows["image_kind"] == "main"].copy()
    else:
        rows = rows.copy()

    for column in text_columns:
        _ensure_text_column(rows, column)

    rows["content_len"] = sum(rows[column].str.len() for column in text_columns)
    return (
        rows.sort_values("content_len", ascending=False)
        .drop_duplicates("slug")
        .copy()
    )


def _merge_text_map(
    df: pd.DataFrame,
    source_rows: pd.DataFrame,
    source_column: str,
    target_column: str,
) -> None:
    _ensure_text_column(df, target_column)
    mapped = df["slug"].map(source_rows.set_index("slug")[source_column].to_dict())
    mapped = mapped.fillna("").astype(str)
    df[target_column] = mapped.where(mapped.str.strip() != "", df[target_column])


def _combine_diagnostics(description: str, ocr_text: str) -> str:
    parts = []
    if description:
        parts.append(f"Description: {description}")
    if ocr_text:
        parts.append(f"OCR: {ocr_text}")
    return "\n\n".join(parts)


def load_data() -> pd.DataFrame:
    """Load comic data and merge stageplay text plus diagnostics."""
    data_path = DATA_PATH_OUT if DATA_PATH_OUT.exists() else DATA_PATH_GOLD

    if not data_path.exists():
        print(f"Data not found at {data_path}. Using mock data.")
        return pd.DataFrame(
            [
                {
                    "slug": "2023-10-01",
                    "date": "2023-10-01",
                    "comic_text": "Panel 1: A guy.\nPanel 2: Another guy.",
                    "hover_text": "A joke about guys.",
                    "votey_text": "The punchline.",
                    "stageplay_script": (
                        "Panel 1.\nGUY: Hello.\nPanel 2.\nOTHER GUY: Hi."
                    ),
                    "diagnostic_accessibility_description": "Two stick figures speak.",
                    "diagnostic_ocr_text": "HELLO.\nHI.",
                    "text_diagnostics_url": "/text-diagnostics/2023-10-01.html",
                }
            ]
        )

    print(f"Loading base data from {data_path}")
    df = pd.read_csv(data_path)

    for column in (
        "comic_text",
        "hover_text",
        "votey_text",
        "stageplay_script",
        "diagnostic_accessibility_description",
        "diagnostic_ocr_text",
    ):
        _ensure_text_column(df, column)

    if VARIANTS_PATH.exists():
        print(f"Incorporating vision diagnostics from {VARIANTS_PATH}")
        best_variants = _load_best_main_rows(
            VARIANTS_PATH,
            ["accessibility_description", "ocr_text"],
        )
        _merge_text_map(
            df,
            best_variants,
            "accessibility_description",
            "diagnostic_accessibility_description",
        )
        _merge_text_map(df, best_variants, "ocr_text", "diagnostic_ocr_text")

    if STAGEPLAY_PATH.exists():
        print(f"Incorporating stageplay text from {STAGEPLAY_PATH}")
        best_stageplay = _load_best_main_rows(
            STAGEPLAY_PATH,
            [
                "stageplay_script",
                "diagnostic_accessibility_description",
                "diagnostic_ocr_text",
            ],
        )
        _merge_text_map(df, best_stageplay, "stageplay_script", "stageplay_script")
        _merge_text_map(
            df,
            best_stageplay,
            "diagnostic_accessibility_description",
            "diagnostic_accessibility_description",
        )
        _merge_text_map(
            df,
            best_stageplay,
            "diagnostic_ocr_text",
            "diagnostic_ocr_text",
        )

    def choose_comic_text(row: pd.Series) -> str:
        if row["stageplay_script"].strip():
            return row["stageplay_script"]
        if row["comic_text"].strip() and row["comic_text"].lower() != "nan":
            return row["comic_text"]
        return _combine_diagnostics(
            row["diagnostic_accessibility_description"],
            row["diagnostic_ocr_text"],
        )

    df["comic_text"] = df.apply(choose_comic_text, axis=1)
    df["has_text_diagnostics"] = (
        df["diagnostic_accessibility_description"].str.strip() != ""
    ) | (df["diagnostic_ocr_text"].str.strip() != "")
    df["text_diagnostics_url"] = df["slug"].map(
        lambda slug: f"/{DIAGNOSTICS_DIR}/{slug}.html"
    )
    df.loc[~df["has_text_diagnostics"], "text_diagnostics_url"] = ""

    initial_count = len(df)
    df = df[df["comic_text"].str.strip() != ""]
    df = df[df["comic_text"].str.lower() != "nan"]

    filtered_count = len(df)
    if filtered_count < initial_count:
        removed = initial_count - filtered_count
        print(
            f"Filtered {removed} comics without usable text. "
            f"{filtered_count} remaining."
        )

    df = df.fillna("")
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date_dt", ascending=False)
    return df


def is_date(text: str) -> bool:
    """Check if text is likely just a date (common in early SMBC hover text)."""
    if not text:
        return False

    import re

    date_patterns = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{1,2}/\d{1,2}/\d{2,4}$",
        r"^[A-Z][a-z]+ \d{1,2}, \d{4}$",
    ]
    return any(re.match(pattern, text.strip()) for pattern in date_patterns)


def generate_site() -> None:
    print("NOTE: Using simple incremental build (skipping existing files).")
    print(
        "      If you modified templates, logic, or data, "
        "run 'make web-clean' first to force a full rebuild."
    )
    setup_directories()
    df = load_data()

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    base_context = {"now": datetime.now(), "is_date": is_date}

    comic_template = env.get_template("comic.html")
    diagnostics_template = env.get_template("diagnostics.html")
    comics = df.to_dict("records")

    import random

    all_slugs = [comic["slug"] for comic in comics]
    shuffled_slugs = all_slugs.copy()
    random.seed(42)
    random.shuffle(shuffled_slugs)

    random_map = {}
    for index, current in enumerate(shuffled_slugs):
        random_map[current] = shuffled_slugs[(index + 1) % len(shuffled_slugs)]

    for index, comic in enumerate(comics):
        slug = comic["slug"]
        output_path = OUTPUT_DIR / "comics" / f"{slug}.html"
        if not output_path.exists():
            prev_slug = comics[index + 1]["slug"] if index + 1 < len(comics) else None
            next_slug = comics[index - 1]["slug"] if index > 0 else None
            html = comic_template.render(
                **base_context,
                comic=comic,
                prev_slug=prev_slug,
                next_slug=next_slug,
                random_slug=random_map.get(slug),
            )
            output_path.write_text(html, encoding="utf-8")
            if index % 100 == 0:
                print(f"Generated {index} comics...")

        if comic["text_diagnostics_url"]:
            diagnostics_path = OUTPUT_DIR / DIAGNOSTICS_DIR / f"{slug}.html"
            if diagnostics_path.exists():
                continue
            diagnostics_html = diagnostics_template.render(
                **base_context,
                comic=comic,
                comic_page_url=f"/comics/{slug}.html",
            )
            diagnostics_path.write_text(diagnostics_html, encoding="utf-8")

    search_template = env.get_template("search.html")
    search_html = search_template.render(**base_context)
    (OUTPUT_DIR / "search.html").write_text(search_html, encoding="utf-8")

    search_index = [
        {
            "slug": comic["slug"],
            "date": comic["date"],
            "text": comic["comic_text"] or "",
            "hover": comic["hover_text"] or "",
        }
        for comic in comics
    ]
    with (OUTPUT_DIR / "search_index.json").open("w", encoding="utf-8") as handle:
        json.dump(search_index, handle)

    about_template = env.get_template("about.html")
    about_html = about_template.render(**base_context)
    (OUTPUT_DIR / "about.html").write_text(about_html, encoding="utf-8")

    if comics:
        latest_comic = comics[0]
        index_html = comic_template.render(
            **base_context,
            comic=latest_comic,
            prev_slug=comics[1]["slug"] if len(comics) > 1 else None,
            next_slug=None,
            random_slug=random_map.get(latest_comic["slug"]),
        )
        (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    if shuffled_slugs:
        first_random = shuffled_slugs[0]
        redirect_html = (
            "<!DOCTYPE html><html><head>"
            '<meta http-equiv="refresh" content="0; '
            f'url=/comics/{first_random}.html?focus=random">'
            "</head><body>Redirecting to random comic...</body></html>"
        )
        (OUTPUT_DIR / "random.html").write_text(redirect_html, encoding="utf-8")

    print(f"Done! Site generated in {OUTPUT_DIR}")


if __name__ == "__main__":
    load_dotenv()
    generate_site()
