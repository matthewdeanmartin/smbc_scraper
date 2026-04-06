from __future__ import annotations

import asyncio
import base64
import csv
import datetime
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import pandas as pd
from loguru import logger
from pydantic import BaseModel
from rich.progress import Progress

from smbc_scraper.core.http import RateLimiter

DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash-lite"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Matches a labeled section header like "OCR_TEXT:" or "SHORT_DESCRIPTION:"
_SECTION_RE = re.compile(
    r"^(OCR_TEXT|SHORT_DESCRIPTION|ACCESSIBILITY_DESCRIPTION):\s*",
    re.IGNORECASE,
)
# Known section labels in order
_SECTION_KEYS = ("OCR_TEXT", "SHORT_DESCRIPTION", "ACCESSIBILITY_DESCRIPTION")

VISION_PROMPT = """You are extracting accessibility metadata from a comic image.
Respond with exactly three labeled sections in this order, nothing else:

OCR_TEXT:
<exact visible text from the image, preserving line breaks; empty if none>

SHORT_DESCRIPTION:
<one concise sentence describing the image>

ACCESSIBILITY_DESCRIPTION:
<concise but complete description for a blind reader: scene, characters, actions, joke setup — no invented details>

Rules:
- Use the section labels exactly as shown.
- Do not add any other text, headings, or formatting.
- Do not invent text that is not visible in the image.
- If text is partially unreadable, include only the readable portions and note uncertainty in ACCESSIBILITY_DESCRIPTION.
"""


class VisionAnalysisRow(BaseModel):
    slug: str
    comic_url: Optional[str] = None
    date: Optional[datetime.date] = None
    page_title: Optional[str] = None
    image_kind: str
    image_path: str
    provider: str
    model: str
    ocr_text: str
    short_description: str
    accessibility_description: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class VisionResult(BaseModel):
    ocr_text: str
    short_description: str
    accessibility_description: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class ImageWorkItem:
    slug: str
    image_kind: str
    image_path: Path
    relative_image_path: str
    comic_url: Optional[str] = None
    comic_date: Optional[datetime.date] = None
    page_title: Optional[str] = None


def parse_vision_response(text: str) -> VisionResult:
    """Parse a labeled-section model response into a VisionResult.

    Expected format (order matters, labels case-insensitive):

        OCR_TEXT:
        <text>

        SHORT_DESCRIPTION:
        <text>

        ACCESSIBILITY_DESCRIPTION:
        <text>

    Text between two section headers belongs to the first header.
    Any content before the first recognized header is discarded.
    """
    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            current_key = m.group(1).upper()
            sections.setdefault(current_key, [])
            # Inline content after the label (e.g. "OCR_TEXT: some text")
            remainder = line[m.end() :]
            if remainder:
                sections[current_key].append(remainder)
        elif current_key is not None:
            sections[current_key].append(line)

    def _get(key: str) -> str:
        lines = sections.get(key, [])
        # Strip trailing blank lines
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()

    if not sections:
        raise ValueError(
            f"Model response contained no recognized section headers. "
            f"Raw response (first 500 chars): {text[:500]!r}"
        )

    return VisionResult(
        ocr_text=_get("OCR_TEXT"),
        short_description=_get("SHORT_DESCRIPTION"),
        accessibility_description=_get("ACCESSIBILITY_DESCRIPTION"),
    )


def encode_image_as_data_url(image_path: Path) -> str:
    """Return a base64 data URL for an image path."""
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type:
        msg = f"Could not determine MIME type for image: {image_path}"
        raise ValueError(msg)

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_date(value: str | None) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        logger.warning(f"Could not parse date value '{value}' from source CSV.")
        return None


def load_comic_metadata(csv_path: Path) -> dict[str, dict[str, Any]]:
    """Load slug-keyed metadata from an export CSV if available."""
    if not csv_path.exists():
        logger.warning(
            f"Source CSV not found: {csv_path}. OCR output will be image-only."
        )
        return {}

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        metadata: dict[str, dict[str, Any]] = {}
        for row in reader:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            metadata[slug] = {
                "comic_url": (row.get("url") or "").strip() or None,
                "comic_date": _parse_date((row.get("date") or "").strip() or None),
                "page_title": (row.get("page_title") or "").strip() or None,
            }
    return metadata


def _parse_image_filename(image_path: Path) -> Optional[tuple[str, str]]:
    stem = image_path.stem
    if stem.endswith("-main"):
        return stem[: -len("-main")], "main"
    if stem.endswith("-votey"):
        return stem[: -len("-votey")], "votey"
    return None


def load_completed_image_paths(output_csv_path: Path) -> set[str]:
    if not output_csv_path.exists():
        return set()

    with output_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            (row.get("image_path") or "").strip()
            for row in reader
            if (row.get("image_path") or "").strip()
        }


def build_image_work_items(
    images_dir: Path,
    source_csv_path: Path,
    existing_output_csv: Optional[Path] = None,
) -> list[ImageWorkItem]:
    """Build image jobs from the local image directory and optional source metadata."""
    metadata = load_comic_metadata(source_csv_path)
    completed_paths = (
        load_completed_image_paths(existing_output_csv)
        if existing_output_csv is not None
        else set()
    )
    data_root = images_dir.parent

    items: list[ImageWorkItem] = []
    for image_path in sorted(images_dir.rglob("*")):
        if (
            not image_path.is_file()
            or image_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES
        ):
            continue

        parsed = _parse_image_filename(image_path)
        if parsed is None:
            logger.debug(
                f"Skipping image with unexpected filename format: {image_path}"
            )
            continue

        slug, image_kind = parsed
        relative_image_path = str(image_path.relative_to(data_root))
        if relative_image_path in completed_paths:
            continue

        meta = metadata.get(slug, {})
        items.append(
            ImageWorkItem(
                slug=slug,
                image_kind=image_kind,
                image_path=image_path,
                relative_image_path=relative_image_path,
                comic_url=meta.get("comic_url"),
                comic_date=meta.get("comic_date"),
                page_title=meta.get("page_title"),
            )
        )

    return items


def save_vision_rows(
    rows: list[VisionAnalysisRow], output_dir: Path, source_name: str
) -> None:
    if not rows:
        logger.warning(f"No OCR rows generated for '{source_name}'.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    data = [row.model_dump() for row in rows]
    df = pd.DataFrame(data)
    column_order = list(VisionAnalysisRow.model_fields)
    df = df[column_order]

    csv_path = output_dir / f"{source_name}.csv"
    xlsx_path = output_dir / f"{source_name}.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_excel(xlsx_path, index=False, engine="openpyxl")
    logger.info(f"Saved {len(df)} OCR rows to {csv_path} and {xlsx_path}")


class OpenRouterVisionClient:
    """Small OpenRouter client for cheap OCR and accessibility descriptions."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENROUTER_MODEL,
        rate_limit: float = 10.0,
        timeout: float = 60.0,
        site_url: Optional[str] = None,
        site_title: str = "smbc_scraper",
    ):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required.")

        headers = {"Authorization": f"Bearer {api_key}"}
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_title:
            headers["X-OpenRouter-Title"] = site_title

        self.model = model
        self.rate_limiter = RateLimiter(rate_limit)
        self.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers=headers,
            timeout=timeout,
        )

    @staticmethod
    def _extract_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text") or ""))
            return "\n".join(part for part in text_parts if part)
        return str(content)

    async def analyze_image(self, image_path: Path) -> VisionResult:
        """Request OCR and a short accessibility description for one image."""
        await self.rate_limiter.wait()

        request_payload = {
            "model": self.model,
            "max_tokens": 600,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": encode_image_as_data_url(image_path),
                            },
                        },
                    ],
                }
            ],
        }

        response = await self.client.post("/chat/completions", json=request_payload)
        if response.status_code != 200:
            logger.error(
                f"OpenRouter API error {response.status_code} for {image_path}: "
                f"{response.text}"
            )
        response.raise_for_status()
        response_data = response.json()
        message = response_data["choices"][0]["message"]
        raw_text = self._extract_message_text(message.get("content"))
        try:
            result = parse_vision_response(raw_text)
        except ValueError:
            logger.error(
                f"Failed to parse response for {image_path}.\nRaw response:\n{raw_text}"
            )
            raise
        usage = response_data.get("usage", {})
        return result.model_copy(
            update={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        )

    async def close(self) -> None:
        await self.client.aclose()


class OpenRouterVisionScraper:
    """Analyzes scraped comic images using OpenRouter vision models."""

    def __init__(
        self,
        client: OpenRouterVisionClient,
        output_dir: Path,
        data_dir: Path,
        source_csv_path: Path,
        output_name: str = "smbc_openrouter_vision",
    ):
        self.client = client
        self.output_dir = output_dir
        self.data_dir = data_dir
        self.images_dir = data_dir / "images"
        self.source_csv_path = source_csv_path
        self.output_name = output_name

    async def scrape(
        self,
        limit: Optional[int] = None,
        overwrite: bool = False,
        concurrency: int = 1,
    ) -> list[VisionAnalysisRow]:
        if not self.images_dir.exists():
            msg = f"Images directory does not exist: {self.images_dir}"
            raise FileNotFoundError(msg)

        existing_output_csv = None
        if not overwrite:
            existing_output_csv = self.output_dir / f"{self.output_name}.csv"

        items = build_image_work_items(
            images_dir=self.images_dir,
            source_csv_path=self.source_csv_path,
            existing_output_csv=existing_output_csv,
        )
        if limit is not None:
            items = items[:limit]

        if not items:
            logger.warning("No images selected for OCR analysis.")
            return []

        logger.info(
            f"Analyzing {len(items)} images with OpenRouter model "
            f"'{self.client.model}'."
        )

        output_csv = self.output_dir / f"{self.output_name}.csv"
        sem = asyncio.Semaphore(concurrency)
        results: list[VisionAnalysisRow] = []
        consecutive_errors = 0
        error_threshold = 50
        stop_event = asyncio.Event()

        async def analyze_item(
            item: ImageWorkItem,
            progress: Progress,
            task_id: Any,
        ) -> Optional[VisionAnalysisRow]:
            if stop_event.is_set():
                return None

            async with sem:
                if stop_event.is_set():
                    return None

                label = f"{item.slug}/{item.image_kind}"
                progress.update(
                    task_id, description=f"[cyan]{self.client.model} · {label}"
                )
                logger.debug(f"Submitting {label} to {self.client.model}")
                try:
                    analysis = await self.client.analyze_image(item.image_path)
                except Exception as exc:
                    logger.error(f"OCR failed for {label}: {exc}")
                    progress.update(task_id, advance=1)
                    return None

                row = VisionAnalysisRow(
                    slug=item.slug,
                    comic_url=item.comic_url,
                    date=item.comic_date,
                    page_title=item.page_title,
                    image_kind=item.image_kind,
                    image_path=item.relative_image_path,
                    provider="openrouter",
                    model=self.client.model,
                    ocr_text=analysis.ocr_text,
                    short_description=analysis.short_description,
                    accessibility_description=analysis.accessibility_description,
                    prompt_tokens=analysis.prompt_tokens,
                    completion_tokens=analysis.completion_tokens,
                    total_tokens=analysis.total_tokens,
                )
                append_vision_rows([row], output_csv)
                logger.info(
                    f"[{self.client.model}] {label} OK "
                    f"(tokens: {analysis.total_tokens}) — "
                    f"{analysis.short_description[:80]}"
                )
                progress.update(task_id, advance=1)
                return row

        with Progress() as progress:
            task_id = progress.add_task(
                f"[cyan]{self.client.model}...", total=len(items)
            )
            coros = [analyze_item(item, progress, task_id) for item in items]
            for future in asyncio.as_completed(coros):
                result = await future
                if result is None:
                    if not stop_event.is_set():
                        consecutive_errors += 1
                        if consecutive_errors >= error_threshold:
                            logger.error(
                                f"Hit {error_threshold} consecutive errors. "
                                f"Stopping model '{self.client.model}'."
                            )
                            stop_event.set()
                else:
                    consecutive_errors = 0
                    results.append(result)

        return results


def get_openrouter_api_key() -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if api_key:
        return api_key
    raise ValueError("Set the OPENROUTER_API_KEY environment variable first.")


# ---------------------------------------------------------------------------
# Multi-model variant helpers
# ---------------------------------------------------------------------------


def load_completed_variant_pairs(output_csv_path: Path) -> set[tuple[str, str]]:
    """Return set of (image_path, model) pairs already present in the variants CSV."""
    if not output_csv_path.exists():
        return set()

    with output_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        pairs: set[tuple[str, str]] = set()
        for row in reader:
            ip = (row.get("image_path") or "").strip()
            model = (row.get("model") or "").strip()
            if ip and model:
                pairs.add((ip, model))
    return pairs


def append_vision_rows(rows: list[VisionAnalysisRow], output_csv_path: Path) -> None:
    """Append rows to an existing (or new) variants CSV without rewriting it."""
    if not rows:
        return

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(VisionAnalysisRow.model_fields)
    file_exists = output_csv_path.exists()

    with output_csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())

    logger.info(f"Appended {len(rows)} rows to {output_csv_path}")


class MultiModelVisionScraper:
    """Runs OCR across multiple models and accumulates results in one variants CSV."""

    def __init__(
        self,
        api_key: str,
        models: list[str],
        output_dir: Path,
        data_dir: Path,
        source_csv_path: Path,
        output_name: str = "smbc_vision_variants",
        rate_limit: float = 10.0,
    ):
        self.api_key = api_key
        self.models = models
        self.output_dir = output_dir
        self.data_dir = data_dir
        self.images_dir = data_dir / "images"
        self.source_csv_path = source_csv_path
        self.output_name = output_name
        self.rate_limit = rate_limit

    async def scrape(
        self,
        limit: Optional[int] = None,
        overwrite: bool = False,
        concurrency: int = 1,
    ) -> list[VisionAnalysisRow]:
        if not self.images_dir.exists():
            raise FileNotFoundError(
                f"Images directory does not exist: {self.images_dir}"
            )

        output_csv = self.output_dir / f"{self.output_name}.csv"
        all_results: list[VisionAnalysisRow] = []

        for model in self.models:
            logger.info(f"Starting OCR with model '{model}'")
            client = OpenRouterVisionClient(
                api_key=self.api_key,
                model=model,
                rate_limit=self.rate_limit,
            )
            try:
                results = await self._run_model(
                    client=client,
                    model=model,
                    output_csv=output_csv,
                    limit=limit,
                    overwrite=overwrite,
                    concurrency=concurrency,
                )
                all_results.extend(results)
            finally:
                await client.close()

        return all_results

    async def _run_model(
        self,
        client: OpenRouterVisionClient,
        model: str,
        output_csv: Path,
        limit: Optional[int],
        overwrite: bool,
        concurrency: int,
    ) -> list[VisionAnalysisRow]:
        done_pairs: set[tuple[str, str]] = set()
        if not overwrite:
            done_pairs = load_completed_variant_pairs(output_csv)

        # Build work items, then filter by (image_path, model) pairs
        all_items = build_image_work_items(
            images_dir=self.images_dir,
            source_csv_path=self.source_csv_path,
        )
        items = [
            item
            for item in all_items
            if (item.relative_image_path, model) not in done_pairs
        ]

        if limit is not None:
            items = items[:limit]

        if not items:
            logger.info(f"No new images to process for model '{model}'.")
            return []

        logger.info(f"Analyzing {len(items)} images with '{model}'.")
        sem = asyncio.Semaphore(concurrency)
        results: list[VisionAnalysisRow] = []
        consecutive_errors = 0
        error_threshold = 50
        stop_event = asyncio.Event()

        async def analyze_item(
            item: ImageWorkItem,
            progress: Progress,
            task_id: Any,
        ) -> Optional[VisionAnalysisRow]:
            if stop_event.is_set():
                return None

            async with sem:
                if stop_event.is_set():
                    return None

                label = f"{item.slug}/{item.image_kind}"
                progress.update(task_id, description=f"[cyan]{model} · {label}")
                logger.debug(f"Submitting {label} to {model}")
                try:
                    analysis = await client.analyze_image(item.image_path)
                except Exception as exc:
                    logger.error(f"OCR failed for {label} ({model}): {exc}")
                    progress.update(task_id, advance=1)
                    return None

                row = VisionAnalysisRow(
                    slug=item.slug,
                    comic_url=item.comic_url,
                    date=item.comic_date,
                    page_title=item.page_title,
                    image_kind=item.image_kind,
                    image_path=item.relative_image_path,
                    provider="openrouter",
                    model=model,
                    ocr_text=analysis.ocr_text,
                    short_description=analysis.short_description,
                    accessibility_description=analysis.accessibility_description,
                    prompt_tokens=analysis.prompt_tokens,
                    completion_tokens=analysis.completion_tokens,
                    total_tokens=analysis.total_tokens,
                )
                # Append immediately so progress survives cancellation
                append_vision_rows([row], output_csv)
                logger.info(
                    f"[{model}] {label} OK "
                    f"(tokens: {analysis.total_tokens}) — "
                    f"{analysis.short_description[:80]}"
                )
                progress.update(task_id, advance=1)
                return row

        with Progress() as progress:
            task_id = progress.add_task(f"[cyan]{model}...", total=len(items))
            coros = [analyze_item(item, progress, task_id) for item in items]
            for future in asyncio.as_completed(coros):
                result = await future
                if result is None:
                    if not stop_event.is_set():
                        consecutive_errors += 1
                        if consecutive_errors >= error_threshold:
                            logger.error(
                                f"Hit {error_threshold} consecutive errors. "
                                f"Stopping model '{model}'."
                            )
                            stop_event.set()
                else:
                    consecutive_errors = 0
                    results.append(result)

        return results


# ---------------------------------------------------------------------------
# Gold synthesis
# ---------------------------------------------------------------------------

GOLD_SYNTHESIS_PROMPT_HEADER = """You are producing the best possible accessibility record for a single comic image.
You have been given OCR and description results from multiple AI models.
Synthesise the most accurate and complete version of each field.

Respond with exactly three labeled sections in this order, nothing else:

GOLD_OCR_TEXT:
<best OCR of the visible text; preserve line breaks; empty if none>

GOLD_SHORT_DESCRIPTION:
<one concise sentence>

GOLD_ACCESSIBILITY_DESCRIPTION:
<detailed scene description for a blind reader; no invented details>

Rules:
- Use the section labels exactly as shown.
- Do not add any other text or formatting.
- Do not invent details not present in any variant.

Variants:
"""

_GOLD_SECTION_RE = re.compile(
    r"^(GOLD_OCR_TEXT|GOLD_SHORT_DESCRIPTION|GOLD_ACCESSIBILITY_DESCRIPTION):\s*",
    re.IGNORECASE,
)


class GoldRow(BaseModel):
    slug: str
    image_kind: str
    image_path: str
    comic_url: Optional[str] = None
    date: Optional[datetime.date] = None
    page_title: Optional[str] = None
    gold_ocr_text: str
    gold_short_description: str
    gold_accessibility_description: str
    models_used: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class GoldResult(BaseModel):
    gold_ocr_text: str
    gold_short_description: str
    gold_accessibility_description: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


def parse_gold_response(text: str) -> GoldResult:
    """Parse a labeled-section gold synthesis response."""
    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in text.splitlines():
        m = _GOLD_SECTION_RE.match(line)
        if m:
            current_key = m.group(1).upper()
            sections.setdefault(current_key, [])
            remainder = line[m.end() :]
            if remainder:
                sections[current_key].append(remainder)
        elif current_key is not None:
            sections[current_key].append(line)

    def _get(key: str) -> str:
        lines = sections.get(key, [])
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()

    if not sections:
        raise ValueError(
            f"Gold response contained no recognized section headers. "
            f"Raw response (first 500 chars): {text[:500]!r}"
        )

    return GoldResult(
        gold_ocr_text=_get("GOLD_OCR_TEXT"),
        gold_short_description=_get("GOLD_SHORT_DESCRIPTION"),
        gold_accessibility_description=_get("GOLD_ACCESSIBILITY_DESCRIPTION"),
    )


def build_synthesis_prompt(variants: list[VisionAnalysisRow]) -> str:
    parts = [GOLD_SYNTHESIS_PROMPT_HEADER]
    for v in variants:
        parts.append(f"<MODEL: {v.model}>")
        parts.append(f"ocr_text: {v.ocr_text}")
        parts.append(f"short_description: {v.short_description}")
        parts.append(f"accessibility_description: {v.accessibility_description}")
        parts.append("")
    return "\n".join(parts)


def load_completed_gold_pairs(output_csv_path: Path) -> set[tuple[str, str]]:
    """Return set of (slug, image_kind) pairs already present in the gold CSV."""
    if not output_csv_path.exists():
        return set()

    with output_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        pairs: set[tuple[str, str]] = set()
        for row in reader:
            slug = (row.get("slug") or "").strip()
            ik = (row.get("image_kind") or "").strip()
            if slug and ik:
                pairs.add((slug, ik))
    return pairs


def load_variants(variants_csv_path: Path) -> list[VisionAnalysisRow]:
    if not variants_csv_path.exists():
        raise FileNotFoundError(f"Variants CSV not found: {variants_csv_path}")

    rows: list[VisionAnalysisRow] = []
    with variants_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                VisionAnalysisRow(
                    slug=row.get("slug", ""),
                    comic_url=row.get("comic_url") or None,
                    date=_parse_date(row.get("date") or None),
                    page_title=row.get("page_title") or None,
                    image_kind=row.get("image_kind", ""),
                    image_path=row.get("image_path", ""),
                    provider=row.get("provider", "openrouter"),
                    model=row.get("model", ""),
                    ocr_text=row.get("ocr_text", ""),
                    short_description=row.get("short_description", ""),
                    accessibility_description=row.get("accessibility_description", ""),
                    prompt_tokens=int(row["prompt_tokens"])
                    if row.get("prompt_tokens")
                    else None,
                    completion_tokens=int(row["completion_tokens"])
                    if row.get("completion_tokens")
                    else None,
                    total_tokens=int(row["total_tokens"])
                    if row.get("total_tokens")
                    else None,
                )
            )
    return rows


def append_gold_rows(rows: list[GoldRow], output_csv_path: Path) -> None:
    if not rows:
        return

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(GoldRow.model_fields)
    file_exists = output_csv_path.exists()

    with output_csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())

    logger.info(f"Appended {len(rows)} gold rows to {output_csv_path}")


class GoldSynthesiser:
    """Submits variant groups to a synthesis LLM and writes gold rows."""

    def __init__(
        self,
        client: OpenRouterVisionClient,
        output_dir: Path,
        output_name: str = "smbc_vision_gold",
    ):
        self.client = client
        self.output_dir = output_dir
        self.output_name = output_name

    async def synthesise(
        self,
        variants_csv: Path,
        limit: Optional[int] = None,
        overwrite: bool = False,
        concurrency: int = 1,
    ) -> list[GoldRow]:
        all_variants = load_variants(variants_csv)

        # Group by (slug, image_kind)
        groups: dict[tuple[str, str], list[VisionAnalysisRow]] = {}
        for v in all_variants:
            key = (v.slug, v.image_kind)
            groups.setdefault(key, []).append(v)

        output_csv = self.output_dir / f"{self.output_name}.csv"
        done_pairs: set[tuple[str, str]] = set()
        if not overwrite:
            done_pairs = load_completed_gold_pairs(output_csv)

        pending = [
            (key, variants)
            for key, variants in sorted(groups.items())
            if key not in done_pairs
        ]
        if limit is not None:
            pending = pending[:limit]

        if not pending:
            logger.info("No new comic images require gold synthesis.")
            return []

        logger.info(f"Synthesising gold for {len(pending)} comic images.")
        sem = asyncio.Semaphore(concurrency)
        results: list[GoldRow] = []
        consecutive_errors = 0
        error_threshold = 50
        stop_event = asyncio.Event()

        async def synthesise_group(
            key: tuple[str, str],
            variants: list[VisionAnalysisRow],
            progress: Progress,
            task_id: Any,
        ) -> Optional[GoldRow]:
            if stop_event.is_set():
                return None

            async with sem:
                if stop_event.is_set():
                    return None

                slug, image_kind = key
                label = f"{slug}/{image_kind}"
                progress.update(task_id, description=f"[cyan]gold · {label}")
                logger.debug(
                    f"Synthesising gold for {label} from {len(variants)} variant(s)"
                )
                prompt = build_synthesis_prompt(variants)
                try:
                    await self.client.rate_limiter.wait()
                    req_payload = {
                        "model": self.client.model,
                        "max_tokens": 900,
                        "temperature": 0,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    response = await self.client.client.post(
                        "/chat/completions", json=req_payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    message = data["choices"][0]["message"]
                    raw_text = OpenRouterVisionClient._extract_message_text(
                        message.get("content")
                    )
                    try:
                        gold = parse_gold_response(raw_text)
                    except ValueError:
                        logger.error(
                            f"Failed to parse gold response for {label}.\n"
                            f"Raw response:\n{raw_text}"
                        )
                        progress.update(task_id, advance=1)
                        return None
                    usage = data.get("usage", {})
                    sample = variants[0]
                    row = GoldRow(
                        slug=slug,
                        image_kind=image_kind,
                        image_path=sample.image_path,
                        comic_url=sample.comic_url,
                        date=sample.date,
                        page_title=sample.page_title,
                        gold_ocr_text=gold.gold_ocr_text,
                        gold_short_description=gold.gold_short_description,
                        gold_accessibility_description=gold.gold_accessibility_description,
                        models_used=",".join(sorted({v.model for v in variants})),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                    )
                    # Append immediately so progress survives cancellation
                    append_gold_rows([row], output_csv)
                    logger.info(
                        f"[gold] {label} OK "
                        f"(tokens: {usage.get('total_tokens')}) — "
                        f"{gold.gold_short_description[:80]}"
                    )
                    progress.update(task_id, advance=1)
                    return row
                except Exception as exc:
                    logger.error(f"Gold synthesis failed for {label}: {exc}")
                    progress.update(task_id, advance=1)
                    return None

        with Progress() as progress:
            task_id = progress.add_task("[cyan]Gold synthesis...", total=len(pending))
            coros = [
                synthesise_group(key, variants, progress, task_id)
                for key, variants in pending
            ]
            for future in asyncio.as_completed(coros):
                result = await future
                if result is None:
                    if not stop_event.is_set():
                        consecutive_errors += 1
                        if consecutive_errors >= error_threshold:
                            logger.error(
                                f"Hit {error_threshold} consecutive gold synthesis errors. Stopping."
                            )
                            stop_event.set()
                else:
                    consecutive_errors = 0
                    results.append(result)

        return results
