# smbc_scraper

Collect raw data from SMBC comics for noble causes, such as machine learning or
creative side projects.

You here for the data? See the [`gold_data`](gold_data) folder.

## Install

Clone the repo and run `uv sync`. This is a repo-first tool, not a PyPI package.

## Use

The CLI entrypoint is `uv run smbc-scrape`.

Common workflows:

- Scrape a fixed ID range:
  `uv run smbc-scrape smbc --start-id 1 --end-id 7500`
- Scrape the full archive and download all images:
  `uv run smbc-scrape smbc-all`
- Incrementally fetch only new comics:
  `uv run smbc-scrape smbc-update`
- Backfill missing images from `out\smbc_ground_truth.csv`:
  `uv run smbc-scrape smbc-images --output-dir out --data-dir data`
- OCR saved comic images with OpenRouter:
  `uv run smbc-scrape ocr --data-dir data --output-dir out`
- Build website-safe comic scripts from vision variants:
  `uv run smbc-scrape ocr-stageplay --variants-csv out\smbc_vision_variants.csv`

Use `--max-rate` to stay polite with the site.

See the docs for the full workflow:

- [`docs/installation.md`](docs/installation.md)
- [`docs/usage.md`](docs/usage.md)
- [`docs/data-layout.md`](docs/data-layout.md)
- [`docs/contributing.md`](docs/contributing.md)
- [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md)
- [`docs/similar-websites.md`](docs/similar-websites.md)
- [`docs/source-material.md`](docs/source-material.md)

`smbc_scraper\sources\that_github_repo.py` is still a direct-run helper rather
than a CLI subcommand.

## Contributing

Fork it, send a change, and please run the checks before opening a PR.


## HTTPX2 migration verification (2026-10-04)

Uses HTTPX2 and Hishel 1.4 HTTPX2 caching with SQLite in the existing cache directory. Old file caches are repopulated, not migrated. 53 selected tests pass on RC3 pre and 3.14, including cache-hit/response-identity and retry regression checks. Declares required Pydantic >=2 and uses supported Selectolax Lexbor parser. Stable RC3 Pydantic wheels remain blocked; external httpbin/paid vision calls not tested.

Dependency locks upgraded and checked. Published dependency wheels only; no native builds or GitHub jobs. Application HTTPX2 objects remain separate from third-party HTTPX objects. Current HTTPX2 releases use the OS trust store. Experimental RC3 tests may require Pydantic prerelease wheels; stable support is reported separately. Changes local; human operators decide releases and upstream reports.
