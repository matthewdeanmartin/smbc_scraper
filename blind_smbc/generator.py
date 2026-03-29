# blind_smbc/generator.py
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

# Configuration
DATA_PATH = Path("../gold_data/smbc_ground_truth.csv")
OUTPUT_DIR = Path("./dist")
TEMPLATES_DIR = Path("./templates")
STATIC_DIR = Path("./static")

def setup_directories():
    """Ensure output directories exist and copy static assets."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "comics").mkdir(exist_ok=True)
    (OUTPUT_DIR / "static").mkdir(exist_ok=True)

    # Copy CSS
    shutil.copy(STATIC_DIR / "style.css", OUTPUT_DIR / "static" / "style.css")

def load_data():
    """Load comic data from CSV."""
    if not DATA_PATH.exists():
        print(f"Data not found at {DATA_PATH}. Using mock data.")
        return pd.DataFrame([
            {
                "slug": "2023-10-01",
                "date": "2023-10-01",
                "comic_text": "Panel 1: A guy.\nPanel 2: Another guy.",
                "hover_text": "A joke about guys.",
                "votey_text": "The punchline."
            }
        ])

    df = pd.read_csv(DATA_PATH)
    # Replace NaN with empty string for Jinja2
    df = df.fillna('')
    # Sort by date descending
    df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.sort_values('date_dt', ascending=False)
    return df

def is_date(text):
    """Check if text is likely just a date (common in early SMBC hover text)."""
    if not text:
        return False
    import re
    # Match YYYY-MM-DD, MM/DD/YY, or Month DD, YYYY
    date_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',
        r'^\d{1,2}/\d{1,2}/\d{2,4}$',
        r'^[A-Z][a-z]+ \d{1,2}, \d{4}$'
    ]
    return any(re.match(p, text.strip()) for p in date_patterns)

def generate_site():
    print("NOTE: Using simple incremental build (skipping existing files).")
    print(
        "      If you modified templates, logic, or data, "
        "run 'make web-clean' first to force a full rebuild."
    )
    setup_directories()
    df = load_data()

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    base_context = {
        "now": datetime.now(),
        "is_date": is_date
    }

    # 1. Generate Individual Comic Pages
    comic_template = env.get_template("comic.html")
    comics = df.to_dict('records')

    # Pre-calculate a shuffled sequence for "Random" navigation
    import random
    all_slugs = [c['slug'] for c in comics]
    shuffled_slugs = all_slugs.copy()
    # Use a fixed seed so the shuffle is stable across runs unless data changes
    random.seed(42)
    random.shuffle(shuffled_slugs)

    # Create a map: slug -> next_shuffled_slug
    random_map = {}
    for i in range(len(shuffled_slugs)):
        current = shuffled_slugs[i]
        nxt = shuffled_slugs[(i + 1) % len(shuffled_slugs)]
        random_map[current] = nxt

    for i, comic in enumerate(comics):
        slug = comic['slug']
        output_path = OUTPUT_DIR / "comics" / f"{slug}.html"

        # Simple Incremental Check: If file exists, skip (for prototype)
        # Note: We skip checking if random_map changed to keep prototype simple,
        # but in production, random_map changes would force a full rebuild.
        if output_path.exists():
            continue

        prev_slug = comics[i+1]['slug'] if i+1 < len(comics) else None
        next_slug = comics[i-1]['slug'] if i > 0 else None

        html = comic_template.render(
            **base_context,
            comic=comic,
            prev_slug=prev_slug,
            next_slug=next_slug,
            random_slug=random_map.get(slug)
        )
        output_path.write_text(html, encoding="utf-8")
        if i % 100 == 0:
            print(f"Generated {i} comics...")

    # 2. Generate Search Page
    search_template = env.get_template("search.html")
    search_html = search_template.render(
        **base_context
    )
    (OUTPUT_DIR / "search.html").write_text(search_html, encoding="utf-8")

    # 2.1 Generate Search Index (Small JSON for client-side search)
    import json
    search_index = []
    for comic in comics:
        search_index.append({
            "slug": comic['slug'],
            "date": comic['date'],
            "text": comic['comic_text'] or "",
            "hover": comic['hover_text'] or ""
        })

    with open(OUTPUT_DIR / "search_index.json", "w", encoding="utf-8") as f:
        json.dump(search_index, f)

    # 2.2 Generate About Page
    about_template = env.get_template("about.html")
    about_html = about_template.render(**base_context)
    (OUTPUT_DIR / "about.html").write_text(about_html, encoding="utf-8")

    # 3. Generate Index Page (Latest Comic)
    if comics:
        latest_comic = comics[0]
        index_html = comic_template.render(
            **base_context,
            comic=latest_comic,
            prev_slug=comics[1]['slug'] if len(comics) > 1 else None,
            next_slug=None,
            random_slug=random_map.get(latest_comic['slug'])
        )
        (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    # 4. Generate Random Redirect Page (Entry Point)
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
    generate_site()
