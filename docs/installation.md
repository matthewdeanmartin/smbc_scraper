# Installation

## Requirements

- Python `>=3.14`
- [`uv`](https://docs.astral.sh/uv/) for dependency management and command
  execution

The project is designed to be run from a clone of the repository rather than
installed as a published package.

## Local setup

```powershell
git clone <your-fork-or-this-repo-url>
cd smbc_scraper
uv sync
```

That installs the runtime dependencies plus the development tools already
declared in `pyproject.toml`.

## Verify the install

```powershell
uv run smbc-scrape --help
make lint
make mypy
make test
```

## Optional capabilities

### Parquet export

`save_comics()` attempts Parquet output when `pyarrow` is available. If it is
missing, CSV and XLSX exports still succeed and the scraper logs a warning.

### OCR and accessibility descriptions

The `ocr` command requires `OPENROUTER_API_KEY`.

```powershell
$env:OPENROUTER_API_KEY = "..."
uv run smbc-scrape ocr --data-dir data --output-dir out
```

The default model is `google/gemini-2.5-flash-lite`, and OCR operates on images
already saved under `data\images\...`.

## Docs tooling

This repo now includes MkDocs and Read the Docs-friendly configuration:

```powershell
make docs-build
make docs-serve
make format-md
make spellcheck
```
