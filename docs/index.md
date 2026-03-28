# SMBC Scraper

`smbc_scraper` is a small, async-first toolkit for collecting SMBC comic data
from the official site and adjacent community sources.

The current CLI supports:

- `smbc` for a fixed legacy ID range from `smbc-comics.com`
- `smbc-all` for the full archive plus image downloads
- `smbc-update` for incremental refreshes using
  `out\smbc_ground_truth_state.json`
- `smbc-images` for backfilling images from an existing metadata export
- `wiki` for transcript scraping from `smbc-wiki.com`
- `ohnorobot` for transcript snippets driven by existing exports
- `ocr` for OCR and accessibility descriptions over saved images

The main outputs live in:

- `out\` for CSV, XLSX, and optional Parquet exports
- `data\html\...` for raw HTML snapshots
- `data\images\...` for main and votey panel images
- `.cache\` for cached HTTP responses

## Quick start

```powershell
uv sync
uv run smbc-scrape --help
uv run smbc-scrape smbc-update
```

If you want OCR or accessibility descriptions, set `OPENROUTER_API_KEY` first
and run `uv run smbc-scrape ocr`.

## Documentation map

- [Installation](installation.md) covers prerequisites and local setup.
- [Usage](usage.md) walks through each command and common workflows.
- [Data layout](data-layout.md) documents outputs, filenames, and schemas.
- [Contributing](contributing.md) covers checks, docs tooling, and PR hygiene.
- [Prior art](PRIOR_ART.md) preserves and expands the project's existing link
  inventory.
- [Similar websites](similar-websites.md) explains the surrounding SMBC web
  ecosystem.
- [Source material](source-material.md) describes the upstream inputs and repo
  artifacts this project builds from.
