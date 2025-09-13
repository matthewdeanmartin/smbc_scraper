#!/usr/bin/env bash
set -euo pipefail

git2md smbc_scraper \
  --ignore __init__.py __pycache__ \
   __about__.py  py.typed \
  --output SOURCE.md