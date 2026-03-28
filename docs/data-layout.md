# Data layout

## Directory structure

The scraper uses three top-level working directories by default:

- `out\` for exports and incremental state
- `data\` for raw HTML and images
- `.cache\` for cached HTTP responses

## Exported files

Most scrapers write a common `ComicRow` export using:

- CSV
- XLSX
- Parquet when `pyarrow` is installed

Typical files:

- `out\smbc_ground_truth.csv`
- `out\smbc_ground_truth.xlsx`
- `out\smbc_ground_truth.parquet`
- `out\smbc_wiki.csv`
- `out\ohnorobot.csv`
- `out\smbc_openrouter_vision.csv`

Incremental official-site updates also use:

- `out\smbc_ground_truth_state.json`

That state file stores a single integer field:

```json
{
  "last_scraped_id": 7645
}
```

## Raw HTML

Official-site scrapes persist HTML snapshots under:

- `data\html\YYYY\MM\DD\<slug>.html`
- `data\html\misc\<slug>.html` for undated pages

## Downloaded images

Official-site images are saved under:

- `data\images\YYYY\MM\DD\<slug>-main.<ext>`
- `data\images\YYYY\MM\DD\<slug>-votey.<ext>`
- `data\images\misc\<slug>-main.<ext>` when a date cannot be inferred

The `ocr` command walks `data\images\...` recursively and keeps the relative
image path in its output rows.

## `ComicRow` schema

Most exports share the `ComicRow` columns below.

| Column | Required | Meaning |
| --- | --- | --- |
| `url` | Yes | Canonical SMBC URL |
| `slug` | Yes | Comic identifier, usually a slug or legacy ID |
| `comic_text` | No | Transcript or text snippet |
| `hover_text` | No | Hover text from the main panel |
| `votey_text` | No | Bonus panel text or transcript |
| `date` | No | Publication date |
| `page_title` | No | HTML page title |
| `source` | Yes | Source label such as `smbc`, `smbc-wiki`, or `ohnorobot` |
| `transcript_quality` | No | Source-specific transcript quality flag |

Rows are sorted chronologically when possible, then by slug and URL, to keep
exports stable across reruns.

## OCR output schema

The `ocr` command writes richer image-level rows with fields like:

- `image_kind`
- `image_path`
- `provider`
- `model`
- `ocr_text`
- `short_description`
- `accessibility_description`
- token usage columns

That output is image-centric rather than comic-centric, so a single comic can
produce multiple rows when both main and votey images exist.
