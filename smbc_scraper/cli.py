# smbc_scraper/cli.py

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
from pathlib import Path

from loguru import logger
from rich.console import Console

from smbc_scraper.core.http import HttpClient
from smbc_scraper.core.logging import setup_logging
from smbc_scraper.export import save_comics
from smbc_scraper.sources.ohnorobot import OhNoRobotScraper
from smbc_scraper.sources.openrouter_vision import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterVisionClient,
    OpenRouterVisionScraper,
    get_openrouter_api_key,
)
from smbc_scraper.sources.smbc import SmbcScraper
from smbc_scraper.sources.smbc_wiki import SmbcWikiScraper

console = Console()


def valid_date(s: str) -> date:
    """Argparse type for validating YYYY-MM-DD date strings."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        msg = f"Not a valid date: '{s}'. Expected YYYY-MM-DD."
        raise argparse.ArgumentTypeError(msg) from exc


async def run_smbc(args: argparse.Namespace):
    """Handler for the 'smbc' subcommand."""
    console.print(
        "[bold yellow]Starting Ground-Truth Scrape from smbc-comics.com[/bold yellow]"
    )
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        results = await scraper.scrape_id_range(args.start_id, args.end_id)
        save_comics(results, args.output_dir, "smbc_ground_truth")
    finally:
        await http_client.close()


async def run_ohnorobot(args: argparse.Namespace):
    """Handler for the 'ohnorobot' subcommand."""
    console.print("[bold yellow]Starting Scrape from ohnorobot.com[/bold yellow]")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = OhNoRobotScraper(http_client)
        # The scraper reads the output_dir to find source CSVs and generate
        # its own queries.
        results = await scraper.scrape(input_dir=args.output_dir, limit=args.limit)
        save_comics(results, args.output_dir, "ohnorobot")
    finally:
        await http_client.close()


async def run_wiki(args: argparse.Namespace):
    """Handler for the 'wiki' subcommand."""
    console.print("[bold yellow]Starting Scrape from smbc-wiki.com API[/bold yellow]")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcWikiScraper(http_client)
        results = await scraper.scrape_id_range(args.start_id, args.end_id)
        save_comics(results, args.output_dir, "smbc_wiki")
    finally:
        await http_client.close()


async def run_ocr(args: argparse.Namespace):
    """Handler for the 'ocr' subcommand."""
    console.print("[bold yellow]Starting cheap OCR via OpenRouter[/bold yellow]")
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    client = OpenRouterVisionClient(
        api_key=get_openrouter_api_key(),
        model=args.model,
        rate_limit=args.max_rate,
    )
    try:
        scraper = OpenRouterVisionScraper(
            client=client,
            output_dir=args.output_dir,
            data_dir=args.data_dir,
            source_csv_path=source_csv,
            output_name=args.output_name,
        )
        await scraper.scrape(
            limit=args.limit,
            overwrite=args.overwrite,
            concurrency=args.concurrency,
        )
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape SMBC comics from multiple sources."
    )

    # Global arguments
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out"),
        help="Directory to save output files.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory to save raw HTML and images.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache"),
        help="Directory for HTTP caching.",
    )
    parser.add_argument(
        "--max-rate", type=float, default=2.0, help="Max requests per second."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level.",
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Available commands"
    )

    # Subcommand for smbc-comics.com
    smbc_parser = subparsers.add_parser(
        "smbc", help="Scrape from the main smbc-comics.com site by ID."
    )
    smbc_parser.add_argument(
        "--start-id", type=int, required=True, help="Start comic ID (e.g., 1)."
    )
    smbc_parser.add_argument(
        "--end-id", type=int, required=True, help="End comic ID (e.g., 7500)."
    )
    smbc_parser.set_defaults(func=run_smbc)

    # Subcommand for ohnorobot.com
    onr_parser = subparsers.add_parser(
        "ohnorobot",
        help="Scrape from ohnorobot.com by generating queries from existing data.",
    )
    onr_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of comics from existing CSVs to use for generating queries.",
    )
    onr_parser.set_defaults(func=run_ohnorobot)

    # Subcommand for smbc-wiki.com
    wiki_parser = subparsers.add_parser(
        "wiki", help="Scrape transcripts from the smbc-wiki.com API by ID."
    )
    wiki_parser.add_argument(
        "--start-id", type=int, required=True, help="Start comic ID (e.g., 1)."
    )
    wiki_parser.add_argument(
        "--end-id", type=int, required=True, help="End comic ID (e.g., 7500)."
    )
    wiki_parser.set_defaults(func=run_wiki)

    # Subcommand for OpenRouter OCR + description
    ocr_parser = subparsers.add_parser(
        "ocr",
        help="Use OpenRouter to OCR local comic images and generate descriptions.",
    )
    ocr_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="CSV file used to enrich OCR output with comic metadata.",
    )
    ocr_parser.add_argument(
        "--model",
        default=DEFAULT_OPENROUTER_MODEL,
        help="OpenRouter multimodal model to use.",
    )
    ocr_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of images to analyze.",
    )
    ocr_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of images to analyze concurrently.",
    )
    ocr_parser.add_argument(
        "--output-name",
        default="smbc_openrouter_vision",
        help="Base filename for OCR exports inside the output directory.",
    )
    ocr_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess images even if they already exist in the output CSV.",
    )
    ocr_parser.set_defaults(func=run_ocr)

    args = parser.parse_args()

    if args.max_rate <= 0:
        parser.error("--max-rate must be > 0")
    if getattr(args, "concurrency", 1) <= 0:
        parser.error("--concurrency must be > 0")

    # Setup logging first
    setup_logging(args.log_level)

    # Run the async function associated with the chosen subcommand
    if hasattr(args, "func"):
        try:
            asyncio.run(args.func(args))
            console.print(
                "\n[bold green]All tasks completed successfully![/bold green]"
            )
        except KeyboardInterrupt:
            console.print("\n[bold red]Operation cancelled by user.[/bold red]")
        except Exception as e:
            console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
            # Use logger for the full traceback if in debug mode
            logger.opt(exception=True).debug("Full exception trace:")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
