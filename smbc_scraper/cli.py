# smbc_scraper/cli.py

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from rich.console import Console

from smbc_scraper.core.http import HttpClient
from smbc_scraper.core.logging import setup_logging
from smbc_scraper.export import load_comics, merge_comics, save_comics
from smbc_scraper.sources.ohnorobot import OhNoRobotScraper
from smbc_scraper.sources.openrouter_vision import (
    DEFAULT_OPENROUTER_MODEL,
    GoldSynthesiser,
    MultiModelVisionScraper,
    OpenRouterVisionClient,
    OpenRouterVisionScraper,
    get_openrouter_api_key,
)
from smbc_scraper.sources.smbc import (
    DEFAULT_INCREMENTAL_STATE_FILENAME,
    IncrementalScrapeState,
    SmbcScraper,
    resolve_incremental_start_id,
    save_incremental_state,
)
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


async def run_smbc_all(args: argparse.Namespace):
    """Handler for scraping the full SMBC archive with images."""
    console.print(
        "[bold yellow]Starting full SMBC archive scrape "
        "with image downloads[/bold yellow]"
    )
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        rows, latest_legacy_id = await scraper.scrape_full_archive(
            start_id=args.start_id or 1, limit=args.limit
        )
        save_comics(rows, args.output_dir, "smbc_ground_truth")
        save_incremental_state(
            args.output_dir / DEFAULT_INCREMENTAL_STATE_FILENAME,
            IncrementalScrapeState(last_scraped_id=latest_legacy_id),
        )
    finally:
        await http_client.close()


async def run_smbc_update(args: argparse.Namespace):
    """Handler for the incremental SMBC update subcommand."""
    console.print("[bold yellow]Starting incremental SMBC update[/bold yellow]")
    state_path = args.state_file or (
        args.output_dir / DEFAULT_INCREMENTAL_STATE_FILENAME
    )
    source_csv = args.output_dir / "smbc_ground_truth.csv"
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        existing_rows = load_comics(source_csv)

        bootstrap_latest_id: int | None = None
        try:
            start_id, previous_state = resolve_incremental_start_id(
                state_path,
                args.start_id,
            )
            new_rows, last_successful_id = await scraper.scrape_incremental(
                start_id=start_id,
                stop_after_missing=args.stop_after_missing,
                max_new_comics=args.limit,
            )
        except ValueError:
            bootstrap_latest_id = await scraper.discover_latest_legacy_id()
            start_id = max(1, bootstrap_latest_id - args.bootstrap_lookback + 1)
            previous_state = None
            console.print(
                "[bold yellow]No saved update state yet; "
                f"bootstrapping from IDs {start_id}..{bootstrap_latest_id}"
                "[/bold yellow]"
            )
            bootstrap_rows = await scraper.scrape_id_range(
                start_id, bootstrap_latest_id
            )
            existing_urls = {str(row.url) for row in existing_rows}
            new_rows = [
                row for row in bootstrap_rows if str(row.url) not in existing_urls
            ]
            last_successful_id = bootstrap_latest_id

        if not new_rows and bootstrap_latest_id is None:
            console.print("[bold green]No new SMBC comics found.[/bold green]")
        elif not new_rows:
            console.print(
                "[bold green]Bootstrap complete; "
                "no new SMBC comics were needed.[/bold green]"
            )
        else:
            merged_rows = merge_comics(existing_rows, new_rows)
            save_comics(merged_rows, args.output_dir, "smbc_ground_truth")

        merged_rows = merge_comics(existing_rows, new_rows)
        prior_last_id = previous_state.last_scraped_id if previous_state else 0
        if last_successful_id is not None and last_successful_id > prior_last_id:
            save_incremental_state(
                state_path, IncrementalScrapeState(last_scraped_id=last_successful_id)
            )
    finally:
        await http_client.close()


async def run_smbc_missing(args: argparse.Namespace):
    """Handler for the 'smbc-missing' subcommand."""
    console.print("[bold yellow]Starting Scrape of missing SMBC IDs[/bold yellow]")
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        existing_rows = load_comics(source_csv)
        new_rows = await scraper.scrape_missing_ids(source_csv)

        if not new_rows:
            console.print("[bold green]No missing SMBC comics found.[/bold green]")
        else:
            merged_rows = merge_comics(existing_rows, new_rows)
            save_comics(merged_rows, args.output_dir, "smbc_ground_truth")
            console.print(
                f"[bold green]Added {len(new_rows)} missing comics.[/bold green]"
            )
    finally:
        await http_client.close()


async def run_smbc_rebuild(args: argparse.Namespace):
    """Handler for the 'smbc-rebuild' subcommand."""
    console.print(
        "[bold yellow]Rebuilding SMBC ID index from local HTML files...[/bold yellow]"
    )
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        updated_rows = await scraper.rebuild_id_index_from_local_files(source_csv)
        save_comics(updated_rows, args.output_dir, "smbc_ground_truth")
        console.print("[bold green]Local index rebuild complete.[/bold green]")
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


async def run_smbc_images(args: argparse.Namespace):
    """Handler for the SMBC image backfill subcommand."""
    console.print("[bold yellow]Starting SMBC image backfill[/bold yellow]")
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    http_client = HttpClient(cache_dir=str(args.cache_dir), rate_limit=args.max_rate)
    try:
        scraper = SmbcScraper(http_client, str(args.data_dir))
        downloaded_images = await scraper.backfill_images(
            source_csv_path=source_csv,
            limit=args.limit,
            overwrite=args.overwrite,
            concurrency=args.concurrency,
        )
        console.print(
            f"[bold green]Downloaded {downloaded_images} SMBC image(s).[/bold green]"
        )
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


async def run_ocr_multi(args: argparse.Namespace):
    """Handler for the 'ocr-multi' subcommand."""
    console.print("[bold yellow]Starting multi-model OCR via OpenRouter[/bold yellow]")
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    scraper = MultiModelVisionScraper(
        api_key=get_openrouter_api_key(),
        models=args.models,
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        source_csv_path=source_csv,
        output_name=args.output_name,
        rate_limit=args.max_rate,
    )
    results = await scraper.scrape(
        limit=args.limit,
        overwrite=args.overwrite,
        concurrency=args.concurrency,
    )
    console.print(f"[bold green]Processed {len(results)} image(s) across {len(args.models)} model(s).[/bold green]")


async def run_ocr_gold(args: argparse.Namespace):
    """Handler for the 'ocr-gold' subcommand."""
    console.print("[bold yellow]Starting gold synthesis via OpenRouter[/bold yellow]")
    source_csv = args.source_csv or (args.output_dir / "smbc_ground_truth.csv")
    variants_csv = args.variants_csv or (args.output_dir / "smbc_vision_variants.csv")
    client = OpenRouterVisionClient(
        api_key=get_openrouter_api_key(),
        model=args.model,
        rate_limit=args.max_rate,
    )
    try:
        synthesiser = GoldSynthesiser(
            client=client,
            output_dir=args.output_dir,
            output_name=args.output_name,
        )
        results = await synthesiser.synthesise(
            variants_csv=variants_csv,
            limit=args.limit,
            overwrite=args.overwrite,
            concurrency=args.concurrency,
        )
        console.print(f"[bold green]Gold synthesis complete: {len(results)} row(s).[/bold green]")
    finally:
        await client.close()


def main():
    load_dotenv()
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
        "--max-rate", type=float, default=10.0, help="Max requests per second."
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

    smbc_all_parser = subparsers.add_parser(
        "smbc-all",
        help="Scrape the full SMBC archive and download all comic images.",
    )
    smbc_all_parser.add_argument(
        "--start-id",
        type=int,
        default=1,
        help="Optional starting legacy ID for a full-archive scrape.",
    )
    smbc_all_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of comics to scrape.",
    )
    smbc_all_parser.set_defaults(func=run_smbc_all)

    smbc_missing_parser = subparsers.add_parser(
        "smbc-missing",
        help="Scrape missing SMBC IDs by comparing existing CSV with the full archive.",
    )
    smbc_missing_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="Existing SMBC CSV export to check for missing IDs.",
    )
    smbc_missing_parser.set_defaults(func=run_smbc_missing)

    smbc_rebuild_parser = subparsers.add_parser(
        "smbc-rebuild",
        help="Rebuild legacy ID index by scanning local HTML files.",
    )
    smbc_rebuild_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="Existing SMBC CSV export to update with discovered IDs.",
    )
    smbc_rebuild_parser.set_defaults(func=run_smbc_rebuild)

    smbc_update_parser = subparsers.add_parser(
        "smbc-update",
        help="Incrementally scrape new SMBC comics using a saved state file.",
    )
    smbc_update_parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Optional path for incremental SMBC state storage.",
    )
    smbc_update_parser.add_argument(
        "--start-id",
        type=int,
        default=None,
        help="Bootstrap start ID to use when no state file exists yet.",
    )
    smbc_update_parser.add_argument(
        "--stop-after-missing",
        type=int,
        default=20,
        help="Stop after this many consecutive missing comic IDs.",
    )
    smbc_update_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of newly discovered comics to save.",
    )
    smbc_update_parser.add_argument(
        "--bootstrap-lookback",
        type=int,
        default=50,
        help=(
            "On first run, scrape this many recent IDs before the discovered "
            "latest one."
        ),
    )
    smbc_update_parser.set_defaults(func=run_smbc_update)

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

    smbc_images_parser = subparsers.add_parser(
        "smbc-images",
        help="Download missing SMBC comic images from an existing metadata CSV.",
    )
    smbc_images_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="Existing SMBC CSV export used to locate canonical comic pages.",
    )
    smbc_images_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of CSV rows to process.",
    )
    smbc_images_parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Number of comic pages to backfill concurrently.",
    )
    smbc_images_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redownload images even if matching local files already exist.",
    )
    smbc_images_parser.set_defaults(func=run_smbc_images)

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

    # Subcommand: ocr-multi — run OCR across multiple models
    ocr_multi_parser = subparsers.add_parser(
        "ocr-multi",
        help="Run OCR across multiple OpenRouter models; accumulate in one variants CSV.",
    )
    ocr_multi_parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="One or more OpenRouter model IDs to use for OCR.",
    )
    ocr_multi_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="CSV file used to enrich OCR output with comic metadata.",
    )
    ocr_multi_parser.add_argument(
        "--output-name",
        default="smbc_vision_variants",
        help="Base filename for the variants CSV inside the output directory.",
    )
    ocr_multi_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on images processed per model.",
    )
    ocr_multi_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of images to analyze concurrently per model.",
    )
    ocr_multi_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess (image_path, model) pairs already in the variants CSV.",
    )
    ocr_multi_parser.set_defaults(func=run_ocr_multi)

    # Subcommand: ocr-gold — synthesise gold record from variants
    ocr_gold_parser = subparsers.add_parser(
        "ocr-gold",
        help="Synthesise a gold OCR+description record from multi-model variants.",
    )
    ocr_gold_parser.add_argument(
        "--variants-csv",
        type=Path,
        default=None,
        help="Variants CSV to read (default: out/smbc_vision_variants.csv).",
    )
    ocr_gold_parser.add_argument(
        "--model",
        default=DEFAULT_OPENROUTER_MODEL,
        help="OpenRouter model used for synthesis.",
    )
    ocr_gold_parser.add_argument(
        "--source-csv",
        type=Path,
        default=None,
        help="Metadata CSV (currently unused but reserved for future enrichment).",
    )
    ocr_gold_parser.add_argument(
        "--output-name",
        default="smbc_vision_gold",
        help="Base filename for the gold CSV inside the output directory.",
    )
    ocr_gold_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on number of comic images to synthesise.",
    )
    ocr_gold_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of synthesis calls to make concurrently.",
    )
    ocr_gold_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-synthesise (slug, image_kind) pairs already in the gold CSV.",
    )
    ocr_gold_parser.set_defaults(func=run_ocr_gold)

    args = parser.parse_args()

    if args.max_rate <= 0:
        parser.error("--max-rate must be > 0")
    if getattr(args, "start_id", 1) is not None and getattr(args, "start_id", 1) <= 0:
        parser.error("--start-id must be > 0")
    if (
        getattr(args, "stop_after_missing", 1) is not None
        and getattr(args, "stop_after_missing", 1) <= 0
    ):
        parser.error("--stop-after-missing must be > 0")
    if (
        getattr(args, "bootstrap_lookback", 1) is not None
        and getattr(args, "bootstrap_lookback", 1) <= 0
    ):
        parser.error("--bootstrap-lookback must be > 0")
    if getattr(args, "limit", 1) is not None and getattr(args, "limit", 1) <= 0:
        parser.error("--limit must be > 0")
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
