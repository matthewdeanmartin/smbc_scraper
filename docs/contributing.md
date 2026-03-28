# Contributing

Thanks for caring enough about weird comic scraping to improve it.

## Development setup

```powershell
uv sync
```

The repo is designed to be worked on in place. There is no separate PyPI
release workflow to target.

## Checks to run before a PR

```powershell
make lint
make mypy
make test
make format-md
make spellcheck
make docs-build
```

Those commands cover Python linting, type-checking, tests, markdown formatting,
docs spelling, and MkDocs validation.

## Documentation expectations

When updating behavior, keep these in sync:

- `README.md` for the short version
- `docs\` for the detailed version
- `Makefile` helpers if command examples change

Please keep `README.md` brief. The detailed explanations should live in the
docs site.

## Writing docs in this repo

- Prefer concrete examples that match the current CLI.
- Use Windows-style paths when referring to repo-local files.
- Preserve the existing history and inventory in `docs\PRIOR_ART.md`; expand it
  with context instead of replacing it wholesale.
- If a helper is not exposed through the CLI, say so plainly.

## Code conventions worth knowing

- The scrapers are async.
- `loguru` handles logging.
- HTTP requests go through the cached, rate-limited `HttpClient`.
- Export order follows the `ComicRow` field order.

## Helpful commands during development

```powershell
make docs-serve
make smbc-update
make smbc-images
```
