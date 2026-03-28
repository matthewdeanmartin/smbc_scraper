# Source material

This page describes the upstream inputs and repo-local artifacts that inform the
current scraper.

## Primary upstreams

### Official SMBC pages

The official site at <https://www.smbc-comics.com> is the primary source of:

- canonical comic URLs
- page titles
- hover text
- main comic images
- bonus "votey" images
- publication dates, when they can be extracted directly or inferred

### SMBC Wiki

The wiki at <https://www.smbc-wiki.com/> is used for transcript-like text and
bonus text extraction through its API-backed pages.

### Oh No Robot

Oh No Robot at <https://www.ohnorobot.com/index.php?comic=137> provides
search-oriented transcript snippets and alternate discovery paths.

## Adjacent datasets

The repo README also points at these materials:

- the Google Sheet:
  <https://docs.google.com/spreadsheets/d/1CH3NX_xKOx-VIPZqp5GkCTHdS7QDsmg7w9Q71Z-aRT0/edit?gid=0#gid=0>
- the GitHub dataset:
  <https://github.com/fricklerhandwerk/smbc>

They are useful for comparison, recovery work, and provenance checks, even
though they are not all exposed through top-level CLI commands.

## Repo-local source artifacts

### `SOURCE.md`

`SOURCE.md` is a generated source dump created by `scripts\make_source.sh`. It
is helpful when reviewing the codebase structure or tracking the current source
layout in one file.

### `gold_data\`

`gold_data\` holds example outputs and reference datasets. The root README still
points data-hungry users there first.

### `smbc_scraper\sources\that_github_repo.py`

This helper parses markdown files with YAML front matter from another
SMBC-related dataset and exports them as `ComicRow` records. It currently stays
outside the main CLI and should be documented as such.

## Provenance and caution

Different sources expose different slices of the truth:

- the official site is canonical for URLs and images
- community sources may provide transcripts or alternate metadata
- OCR output is derived data and should be treated as enrichment, not ground
  truth

That distinction is why the repo keeps source-specific exports instead of
flattening everything into one silently merged file.
