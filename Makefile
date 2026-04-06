ifneq (,$(wildcard ./.env))
    include .env
    export
endif

PYTHON ?= uv run
SCRAPER := $(PYTHON) smbc-scrape
LOG_LEVEL ?= INFO
MAX_RATE ?= 10.0
OUTPUT_DIR ?= out
DATA_DIR ?= data
CACHE_DIR ?= .cache
DOCS_FILES := README.md docs

.PHONY: help sync test lint mypy ty check docs docs-build docs-serve format-md spellcheck smbc smbc-all smbc-fill-in-missing smbc-rebuild smbc-update smbc-images wiki ohnorobot ocr ocr-multi ocr-gold web-gen web-clean web-serve web-open

help:
	@echo "Targets:"
	@echo "  make sync"
	@echo "  make test"
	@echo "  make lint"
	@echo "  make mypy"
	@echo "  make ty"
	@echo "  make check"
	@echo "  make docs-build"
	@echo "  make docs-serve"
	@echo "  make format-md"
	@echo "  make spellcheck"
	@echo "  make smbc START_ID=1 END_ID=7645"
	@echo "  make smbc-all"
	@echo "  make smbc-fill-in-missing"
	@echo "  make smbc-rebuild"
	@echo "  make smbc-update [START_ID=7501] [BOOTSTRAP_LOOKBACK=50]"
	@echo "  make smbc-images"
	@echo "  make wiki START_ID=1 END_ID=7645"
	@echo "  make ohnorobot LIMIT=100"
	@echo "  make ocr"
	@echo "  make ocr-multi MODELS='model1 model2'  - OCR with multiple models → variants CSV"
	@echo "  make ocr-gold [GOLD_MODEL=...]          - Synthesise gold from variants CSV"
	@echo "  make web-gen          - Generate the accessible static site"
	@echo "  make web-clean        - Remove the generated static site"
	@echo "  make web-serve        - Serve the generated site locally"
	@echo "  make web-open         - Generate, open in browser, and serve"

sync:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .

mypy:
	uv run mypy smbc_scraper test

ty:
	uv run ty check smbc_scraper test

check: lint mypy ty test

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
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-all $(if $(LIMIT),--limit "$(LIMIT)",)

smbc-fill-in-missing:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-missing

smbc-rebuild:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" smbc-rebuild

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

# MODELS="google/gemini-2.5-flash-lite anthropic/claude-3.5-haiku" make ocr-multi
ocr-multi:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" ocr-multi --models $(MODELS) $(if $(LIMIT),--limit "$(LIMIT)",) $(if $(CONCURRENCY),--concurrency "$(CONCURRENCY)",)

# GOLD_MODEL="google/gemini-2.5-flash" make ocr-gold
ocr-gold:
	$(SCRAPER) --log-level "$(LOG_LEVEL)" --max-rate "$(MAX_RATE)" --output-dir "$(OUTPUT_DIR)" --data-dir "$(DATA_DIR)" --cache-dir "$(CACHE_DIR)" ocr-gold $(if $(GOLD_MODEL),--model "$(GOLD_MODEL)",) $(if $(LIMIT),--limit "$(LIMIT)",) $(if $(CONCURRENCY),--concurrency "$(CONCURRENCY)",)

web-gen:
	cd blind_smbc && $(PYTHON) python generator.py

web-clean:
	powershell -Command "if (Test-Path blind_smbc/dist) { Remove-Item -Recurse -Force blind_smbc/dist }"

web-serve:
	cd blind_smbc/dist && python -m http.server 8000

web-open: web-gen
	start http://localhost:8000 && cd blind_smbc/dist && python -m http.server 8000
