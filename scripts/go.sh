#!/bin/bash

# ==============================================================================
# SMBC Scraper Execution Script
# ==============================================================================
#
# This script automates running the SMBC scraper with different source commands.


# --- Configuration ---
set -e  # Exit immediately if a command exits with a non-zero status.
set -o pipefail # Exit status of the last command that threw a non-zero exit code is returned.

LOG_LEVEL=INFO

echo "Installing/updating dependencies from pyproject.toml..."
uv sync
echo "Dependencies are up to date."
echo ""

# ==============================================================================
# EXECUTE SCRAPER COMMANDS
# ==============================================================================

# ---
# Ground-Truth Scrape from smbc-comics.com
# Downloads HTML and images to the 'data/' directory.
#
echo "--- Running Ground-Truth Scraper for 2024 ---"
# smbc-scrape --log-level "$LOG_LEVEL" --max-rate 2 smbc --start-id 1 --end-id 7645


# ---
# SMBC-Wiki API Scrape
# Searches the wiki for pages related to specific topics and parses them.
# Also fast and API-based.
#
echo "--- Running SMBC-Wiki Scraper ---"
smbc-scrape --log-level "$LOG_LEVEL" wiki --start-id 1 --end-id 7645

# ---
# Oh No Robot Scrape
# Scrapes transcript snippets for common SMBC themes.
# Note: This is faster as it doesn't download images.
#
echo "--- Running Oh No Robot Scraper ---"
# smbc-scrape --log-level "$LOG_LEVEL" ohnorobot --limit 7645

# ==============================================================================

echo ""
echo "--- Script finished ---"

