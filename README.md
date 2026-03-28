# smbc_scraper
Collect raw data from smbc comics for noble causes, such as machine learning or creative side projects.

You here for the data? See the [gold_data](gold_data) folder.

## Major Data Sources

- [SMBC-comics.com](https://www.smbc-comics.com)
- [That Google Doc](https://docs.google.com/spreadsheets/d/1CH3NX_xKOx-VIPZqp5GkCTHdS7QDsmg7w9Q71Z-aRT0/edit?gid=0#gid=0)
- [That Github Repo](https://github.com/fricklerhandwerk/smbc)
- [That Wiki](https://www.smbc-wiki.com/)
- [Ohnorobot](http://www.ohnorobot.com/index.php?comic=137)

## Installation

Git clone it. Run `uv sync`. This will never be a pypi package.

## Usage

It has a CLI, see [/scripts/go.sh](scripts/go.sh) for example usage.

`that_github_repo.py` you have to run it directly

For the official site, you can now:

- scrape a fixed ID range:
  `uv run smbc-scrape smbc --start-id 1 --end-id 7500`
- scrape the full archive and download all images:
  `uv run smbc-scrape smbc-all`
- incrementally fetch only new comics after a previous run:
  `uv run smbc-scrape smbc-update`
  If there is no state file yet, it will discover the current legacy archive
  boundary from the site, scrape a recent bootstrap window, and then save
  `out\smbc_ground_truth_state.json` for later runs. You can still force a
  manual bootstrap with `--start-id 7501`.
  After the first successful run, `smbc-update` will reuse
  `out\smbc_ground_truth_state.json`.
- backfill missing local images from an existing metadata export:
  `uv run smbc-scrape smbc-images --output-dir out --data-dir data`
  This only backfills images for comics already present in
  `out\smbc_ground_truth.csv`.

Use `--max-rate` to stay polite with the site.

There is also a `Makefile` with helper targets like `make smbc-all`,
`make smbc-update`, and `make smbc-images`.

For cheap OCR and image descriptions from saved comic images, set
`OPENROUTER_API_KEY` and run:

`uv run smbc-scrape ocr --data-dir data --output-dir out`

## Contributing

Fork and MR and if you're lucky I'll respond in days.

## Prior Art

See [docs/PRIOR_ART.md](docs/PRIOR_ART.md)
