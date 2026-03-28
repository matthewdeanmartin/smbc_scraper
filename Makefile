PYTHON ?= uv run
SCRAPER := $(PYTHON) smbc-scrape
LOG_LEVEL ?= INFO
MAX_RATE ?= 1.0
OUTPUT_DIR ?= out
DATA_DIR ?= data
CACHE_DIR ?= .cache
DOCS_FILES := README.md docs

.PHONY: help sync test lint mypy docs docs-build docs-serve format-md spellcheck smbc smbc-all smbc-update smbc-images wiki ohnorobot ocr

help:
	@echo "Targets:"
	@echo "  make sync"
	@echo "  make test"
	@echo "  make lint"
	@echo "  make mypy"
	@echo "  make docs-build"
	@echo "  make docs-serve"
	@echo "  make format-md"
	@echo "  make spellcheck"
	@echo "  make smbc START_ID=1 END_ID=7645"
	@echo "  make smbc-all"
	@echo "  make smbc-update [START_ID=7501] [BOOTSTRAP_LOOKBACK=50]"
	@echo "  make smbc-images"
	@echo "  make wiki START_ID=1 END_ID=7645"
	@echo "  make ohnorobot LIMIT=100"
	@echo "  make ocr"

sync:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .

mypy:
	uv run mypy smbc_scraper test

docs: docs-build

docs-build:
	uv run mkdocs build --strict

docs-serve:
	uv run mkdocs serve

format-md:
	uv run mdformat $(DOCS_FILES)

spellcheck:
	uv run codespell README.md docs

smbc:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc --start-id "$(START_ID)" --end-id "$(END_ID)"

smbc-all:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-all

smbc-update:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-update $(if $(START_ID),--start-id "$(START_ID)",) $(if $(BOOTSTRAP_LOOKBACK),--bootstrap-lookback "$(BOOTSTRAP_LOOKBACK)",)

smbc-images:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-images

wiki:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" wiki --start-id "$(START_ID)" --end-id "$(END_ID)"

ohnorobot:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" ohnorobot --limit "$(LIMIT)"

ocr:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" ocr
