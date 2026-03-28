# Usage

The CLI entrypoint is:

```powershell
uv run smbc-scrape --help
```

All subcommands share these global options:

- `--output-dir` for exported files, default `out`
- `--data-dir` for raw HTML and downloaded images, default `data`
- `--cache-dir` for HTTP caching, default `.cache`
- `--max-rate` for polite request pacing, default `2.0`
- `--log-level` with `DEBUG`, `INFO`, `WARNING`, or `ERROR`

## Command reference

### `smbc`

Scrape a fixed legacy ID range from the official site.

```powershell
uv run smbc-scrape smbc --start-id 1 --end-id 7500
```

Use this when you want a bounded scrape, a reproducible batch, or a smaller
refresh than `smbc-all`.

### `smbc-all`

Scrape the full archive from ID `1` through the latest discovered legacy ID and
download the associated images.

```powershell
uv run smbc-scrape smbc-all
uv run smbc-scrape smbc-all --start-id 7000
```

This writes `out\smbc_ground_truth.*` and updates
`out\smbc_ground_truth_state.json`.

### `smbc-update`

Incrementally discover only new comics after a prior run.

```powershell
uv run smbc-scrape smbc-update
uv run smbc-scrape smbc-update --start-id 7501
uv run smbc-scrape smbc-update --bootstrap-lookback 100
```

Behavior:

- If `out\smbc_ground_truth_state.json` exists, the scraper starts at the next
  legacy ID.
- If no state file exists, it discovers the current archive boundary, scrapes a
  recent bootstrap window, merges any new rows into `out\smbc_ground_truth.csv`,
  and writes the state file for next time.
- `--stop-after-missing` controls how many consecutive empty IDs count as the
  end of new material.
- `--limit` lets you cap the number of newly saved comics.

### `smbc-images`

Backfill missing local images using an existing metadata export.

```powershell
uv run smbc-scrape smbc-images
uv run smbc-scrape smbc-images --limit 100 --concurrency 4
uv run smbc-scrape smbc-images --overwrite
```

By default it reads `out\smbc_ground_truth.csv`, revisits each comic page, and
downloads only missing `-main` and `-votey` images under `data\images\...`.

### `wiki`

Scrape transcript-oriented data from the `smbc-wiki.com` MediaWiki API.

```powershell
uv run smbc-scrape wiki --start-id 1 --end-id 7645
```

This is useful for transcript enrichment and bonus text that may not be
captured directly from the official site.

### `ohnorobot`

Generate search queries from the titles in existing exports and pull transcript
snippets from Oh No Robot.

```powershell
uv run smbc-scrape ohnorobot --limit 100
```

This command expects at least one of these to exist in `out\`:

- `smbc_ground_truth.csv`
- `smbc_wiki.csv`

### `ocr`

Analyze saved comic images with OpenRouter for OCR, short descriptions, and
accessibility descriptions.

```powershell
$env:OPENROUTER_API_KEY = "..."
uv run smbc-scrape ocr --data-dir data --output-dir out
uv run smbc-scrape ocr --limit 25 --concurrency 2 --overwrite
```

The output defaults to `out\smbc_openrouter_vision.csv` and
`out\smbc_openrouter_vision.xlsx`.

## Common workflows

### First full local dataset

```powershell
make sync
make smbc-all
make wiki START_ID=1 END_ID=7645
make ohnorobot LIMIT=100
```

### Regular refresh of official-site data

```powershell
make smbc-update
make smbc-images
```

### Accessibility enrichment

```powershell
$env:OPENROUTER_API_KEY = "..."
make ocr
```

## Makefile shortcuts

The Makefile wraps the main workflows:

- `make smbc START_ID=1 END_ID=7645`
- `make smbc-all`
- `make smbc-update [START_ID=7501] [BOOTSTRAP_LOOKBACK=50]`
- `make smbc-images`
- `make wiki START_ID=1 END_ID=7645`
- `make ohnorobot LIMIT=100`
- `make ocr`

## One direct-run helper

`smbc_scraper\sources\that_github_repo.py` is not wired into the CLI. It is a
separate helper for parsing markdown content from another SMBC-related dataset.
