from __future__ import annotations

import asyncio
import base64
import csv
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import date
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
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(?P<body>\{.*\})\s*```", re.DOTALL)
JSON_OBJECT_RE = re.compile(r"(?P<body>\{.*\})", re.DOTALL)

VISION_PROMPT = """You are extracting accessibility metadata from a comic image.
Return a single JSON object with exactly these keys:
- ocr_text: exact visible text from the image. Preserve line breaks when
  possible. Use an empty string if no readable text is present.
- short_description: one concise sentence describing the image.
- accessibility_description: a concise but useful description for a blind
  reader that explains the important visual scene, actions, and joke setup
  without inventing details.

Rules:
- Output JSON only.
- Do not use markdown fences.
- Do not invent text that is not visible.
- If text is partially unreadable, include only the readable portions and
  mention uncertainty in accessibility_description.
"""


class VisionAnalysisRow(BaseModel):
    slug: str
    comic_url: Optional[str] = None
    date: Optional[date] = None
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
    comic_date: Optional[date] = None
    page_title: Optional[str] = None


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if match := JSON_BLOCK_RE.fullmatch(stripped):
        return match.group("body")
    return stripped


def parse_json_response(text: str) -> VisionResult:
    """Parse the model response into a normalized VisionResult."""
    candidate = _strip_code_fences(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        match = JSON_OBJECT_RE.search(candidate)
        if not match:
            raise ValueError("Model response did not contain a JSON object.") from None
        payload = json.loads(match.group("body"))

    if not isinstance(payload, dict):
        raise ValueError("Model response JSON was not an object.")

    return VisionResult(
        ocr_text=str(payload.get("ocr_text") or "").strip(),
        short_description=str(payload.get("short_description") or "").strip(),
        accessibility_description=str(
            payload.get("accessibility_description") or ""
        ).strip(),
    )


def encode_image_as_data_url(image_path: Path) -> str:
    """Return a base64 data URL for an image path."""
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type:
        msg = f"Could not determine MIME type for image: {image_path}"
        raise ValueError(msg)

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
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
        rate_limit: float = 1.0,
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

        payload = {
            "model": self.model,
            "max_tokens": 500,
            "temperature": 0,
            "response_format": {"type": "json_object"},
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

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]
        result = parse_json_response(self._extract_message_text(message.get("content")))
        usage = payload.get("usage", {})

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

        sem = asyncio.Semaphore(concurrency)
        results: list[VisionAnalysisRow] = []

        async def analyze_item(item: ImageWorkItem) -> Optional[VisionAnalysisRow]:
            async with sem:
                try:
                    analysis = await self.client.analyze_image(item.image_path)
                except Exception as exc:
                    logger.error(f"OpenRouter OCR failed for {item.image_path}: {exc}")
                    return None

                return VisionAnalysisRow(
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

        with Progress() as progress:
            task = progress.add_task("[cyan]Analyzing images...", total=len(items))
            tasks = [analyze_item(item) for item in items]
            for future in asyncio.as_completed(tasks):
                result = await future
                if result is not None:
                    results.append(result)
                progress.update(task, advance=1)

        results.sort(key=lambda row: (row.slug, row.image_kind))
        save_vision_rows(results, self.output_dir, self.output_name)
        return results


def get_openrouter_api_key() -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if api_key:
        return api_key
    raise ValueError("Set the OPENROUTER_API_KEY environment variable first.")
