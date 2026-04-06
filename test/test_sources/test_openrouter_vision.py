from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from smbc_scraper.sources.openrouter_vision import (
    GoldRow,
    MultiModelVisionScraper,
    OpenRouterVisionClient,
    VisionAnalysisRow,
    append_vision_rows,
    build_image_work_items,
    build_synthesis_prompt,
    encode_image_as_data_url,
    load_completed_gold_pairs,
    load_completed_variant_pairs,
    parse_gold_response,
    parse_vision_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00"
        b"\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _make_variant(slug: str, image_kind: str, model: str, image_path: str = "") -> VisionAnalysisRow:
    return VisionAnalysisRow(
        slug=slug,
        image_kind=image_kind,
        image_path=image_path or f"images/2024/01/01/{slug}-{image_kind}.png",
        provider="openrouter",
        model=model,
        ocr_text="Some text",
        short_description="A comic.",
        accessibility_description="A scene description.",
    )


# ---------------------------------------------------------------------------
# parse_vision_response
# ---------------------------------------------------------------------------


def test_parse_vision_response_happy_path() -> None:
    text = (
        "OCR_TEXT:\nHello world\nline two\n\n"
        "SHORT_DESCRIPTION:\nA test image.\n\n"
        "ACCESSIBILITY_DESCRIPTION:\nA scientist explains things.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == "Hello world\nline two"
    assert result.short_description == "A test image."
    assert result.accessibility_description == "A scientist explains things."


def test_parse_vision_response_inline_value() -> None:
    """Label and value on the same line."""
    text = (
        "OCR_TEXT: Single line text\n"
        "SHORT_DESCRIPTION: One sentence.\n"
        "ACCESSIBILITY_DESCRIPTION: Scene.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == "Single line text"
    assert result.short_description == "One sentence."


def test_parse_vision_response_case_insensitive() -> None:
    text = (
        "ocr_text:\nTEXT\n"
        "short_description:\nDesc.\n"
        "accessibility_description:\nScene.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == "TEXT"


def test_parse_vision_response_empty_ocr() -> None:
    text = (
        "OCR_TEXT:\n\n"
        "SHORT_DESCRIPTION:\nNo text visible.\n"
        "ACCESSIBILITY_DESCRIPTION:\nBlank panel.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == ""
    assert result.short_description == "No text visible."


def test_parse_vision_response_missing_sections_raises() -> None:
    with pytest.raises(ValueError, match="no recognized section headers"):
        parse_vision_response("this is garbage with no labels")


def test_parse_vision_response_error_includes_raw_text() -> None:
    raw = "model said something unexpected"
    with pytest.raises(ValueError) as exc_info:
        parse_vision_response(raw)
    assert raw in str(exc_info.value)


def test_parse_vision_response_multiline_ocr_preserved() -> None:
    text = (
        "OCR_TEXT:\nLine 1\nLine 2\nLine 3\n\n"
        "SHORT_DESCRIPTION:\nThree lines.\n"
        "ACCESSIBILITY_DESCRIPTION:\nThree-line panel.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == "Line 1\nLine 2\nLine 3"


def test_parse_vision_response_ignores_preamble() -> None:
    """Any text before the first label is discarded."""
    text = (
        "Sure, here is the metadata:\n\n"
        "OCR_TEXT:\nExtracted text\n"
        "SHORT_DESCRIPTION:\nA desc.\n"
        "ACCESSIBILITY_DESCRIPTION:\nA scene.\n"
    )
    result = parse_vision_response(text)
    assert result.ocr_text == "Extracted text"


# ---------------------------------------------------------------------------
# parse_gold_response
# ---------------------------------------------------------------------------


def test_parse_gold_response_happy_path() -> None:
    text = (
        "GOLD_OCR_TEXT:\nBest OCR\n\n"
        "GOLD_SHORT_DESCRIPTION:\nBest sentence.\n\n"
        "GOLD_ACCESSIBILITY_DESCRIPTION:\nBest scene description.\n"
    )
    result = parse_gold_response(text)
    assert result.gold_ocr_text == "Best OCR"
    assert result.gold_short_description == "Best sentence."
    assert result.gold_accessibility_description == "Best scene description."


def test_parse_gold_response_missing_sections_raises() -> None:
    with pytest.raises(ValueError, match="no recognized section headers"):
        parse_gold_response("nonsense output")


def test_parse_gold_response_error_includes_raw_text() -> None:
    raw = "unexpected model output"
    with pytest.raises(ValueError) as exc_info:
        parse_gold_response(raw)
    assert raw in str(exc_info.value)


# ---------------------------------------------------------------------------
# build_synthesis_prompt
# ---------------------------------------------------------------------------


def test_build_synthesis_prompt_contains_all_models() -> None:
    variants = [
        _make_variant("slug-a", "main", "model-alpha"),
        _make_variant("slug-a", "main", "model-beta"),
    ]
    prompt = build_synthesis_prompt(variants)
    assert "model-alpha" in prompt
    assert "model-beta" in prompt
    assert "GOLD_OCR_TEXT:" in prompt
    assert "GOLD_SHORT_DESCRIPTION:" in prompt
    assert "GOLD_ACCESSIBILITY_DESCRIPTION:" in prompt
    assert "Some text" in prompt


# ---------------------------------------------------------------------------
# encode_image_as_data_url
# ---------------------------------------------------------------------------


def test_encode_image_as_data_url_uses_image_mime_type(
    tmp_path: Path, png_bytes: bytes
) -> None:
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)
    data_url = encode_image_as_data_url(image_path)
    assert data_url.startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# build_image_work_items
# ---------------------------------------------------------------------------


def test_build_image_work_items_joins_metadata_and_skips_completed(
    tmp_path: Path, png_bytes: bytes
) -> None:
    images_dir = tmp_path / "data" / "images" / "2024" / "09" / "01"
    images_dir.mkdir(parents=True)
    (images_dir / "critical-main.png").write_bytes(png_bytes)
    (images_dir / "critical-votey.png").write_bytes(png_bytes)

    source_csv = tmp_path / "smbc_ground_truth.csv"
    source_csv.write_text(
        "url,slug,date,page_title\n"
        "https://www.smbc-comics.com/comic/critical,critical,2024-09-01,Critical\n",
        encoding="utf-8",
    )

    existing_output = tmp_path / "smbc_openrouter_vision.csv"
    existing_output.write_text(
        "image_path\nimages\\2024\\09\\01\\critical-votey.png\n",
        encoding="utf-8",
    )

    items = build_image_work_items(
        tmp_path / "data" / "images",
        source_csv,
        existing_output,
    )

    assert len(items) == 1
    assert items[0].slug == "critical"
    assert items[0].image_kind == "main"
    assert items[0].comic_url == "https://www.smbc-comics.com/comic/critical"
    assert items[0].comic_date == date(2024, 9, 1)
    assert items[0].page_title == "Critical"


def test_build_image_work_items_skips_unknown_filename(
    tmp_path: Path, png_bytes: bytes
) -> None:
    images_dir = tmp_path / "data" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "no-suffix.png").write_bytes(png_bytes)  # no -main/-votey
    source_csv = tmp_path / "gt.csv"
    source_csv.write_text("url,slug,date,page_title\n", encoding="utf-8")

    items = build_image_work_items(images_dir, source_csv)
    assert items == []


# ---------------------------------------------------------------------------
# load_completed_variant_pairs / append_vision_rows
# ---------------------------------------------------------------------------


def test_load_completed_variant_pairs_empty_when_no_file(tmp_path: Path) -> None:
    pairs = load_completed_variant_pairs(tmp_path / "nonexistent.csv")
    assert pairs == set()


def test_append_and_reload_variant_pairs(tmp_path: Path) -> None:
    csv_path = tmp_path / "variants.csv"
    rows = [
        _make_variant("slug1", "main", "model-a", "images/slug1-main.png"),
        _make_variant("slug1", "votey", "model-b", "images/slug1-votey.png"),
    ]
    append_vision_rows(rows, csv_path)
    pairs = load_completed_variant_pairs(csv_path)
    assert ("images/slug1-main.png", "model-a") in pairs
    assert ("images/slug1-votey.png", "model-b") in pairs


def test_append_vision_rows_is_additive(tmp_path: Path) -> None:
    csv_path = tmp_path / "variants.csv"
    row_a = _make_variant("slug1", "main", "model-a", "images/slug1-main.png")
    row_b = _make_variant("slug2", "main", "model-a", "images/slug2-main.png")

    append_vision_rows([row_a], csv_path)
    append_vision_rows([row_b], csv_path)

    pairs = load_completed_variant_pairs(csv_path)
    assert len(pairs) == 2
    assert ("images/slug1-main.png", "model-a") in pairs
    assert ("images/slug2-main.png", "model-a") in pairs


# ---------------------------------------------------------------------------
# load_completed_gold_pairs
# ---------------------------------------------------------------------------


def test_load_completed_gold_pairs_empty_when_no_file(tmp_path: Path) -> None:
    pairs = load_completed_gold_pairs(tmp_path / "nonexistent.csv")
    assert pairs == set()


def test_load_completed_gold_pairs_reads_existing(tmp_path: Path) -> None:
    csv_path = tmp_path / "gold.csv"
    fieldnames = list(GoldRow.model_fields)
    import csv as csv_mod
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "slug": "my-slug", "image_kind": "main", "image_path": "p",
            "comic_url": None, "date": None, "page_title": None,
            "gold_ocr_text": "", "gold_short_description": "",
            "gold_accessibility_description": "", "models_used": "m",
            "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        })

    pairs = load_completed_gold_pairs(csv_path)
    assert ("my-slug", "main") in pairs


# ---------------------------------------------------------------------------
# OpenRouterVisionClient.analyze_image — integration with new parser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_client_parses_section_response(
    tmp_path: Path, png_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)
    client = OpenRouterVisionClient(api_key="test-key")

    section_response = (
        "OCR_TEXT:\nTEXT HERE\n\n"
        "SHORT_DESCRIPTION:\nShort.\n\n"
        "ACCESSIBILITY_DESCRIPTION:\nLonger description.\n"
    )

    async def fake_post(url: str, json: dict):
        return DummyResponse({
            "choices": [{"message": {"content": section_response}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
        })

    monkeypatch.setattr(client.client, "post", fake_post)
    try:
        result = await client.analyze_image(image_path)
    finally:
        await client.close()

    assert result.ocr_text == "TEXT HERE"
    assert result.short_description == "Short."
    assert result.accessibility_description == "Longer description."
    assert result.prompt_tokens == 123
    assert result.total_tokens == 168


@pytest.mark.asyncio
async def test_openrouter_client_does_not_send_response_format(
    tmp_path: Path, png_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify response_format is not sent (constrains models unnecessarily)."""
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)
    client = OpenRouterVisionClient(api_key="test-key")
    captured: dict = {}

    async def fake_post(url: str, json: dict):
        captured["json"] = json
        return DummyResponse({
            "choices": [{"message": {"content": "OCR_TEXT:\n\nSHORT_DESCRIPTION:\nX.\nACCESSIBILITY_DESCRIPTION:\nY.\n"}}],
            "usage": {},
        })

    monkeypatch.setattr(client.client, "post", fake_post)
    try:
        await client.analyze_image(image_path)
    finally:
        await client.close()

    assert "response_format" not in captured["json"]


@pytest.mark.asyncio
async def test_openrouter_client_raises_on_bad_response(
    tmp_path: Path, png_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)
    client = OpenRouterVisionClient(api_key="test-key")

    async def fake_post(url: str, json: dict):
        return DummyResponse({
            "choices": [{"message": {"content": "this is not a valid response"}}],
            "usage": {},
        })

    monkeypatch.setattr(client.client, "post", fake_post)
    try:
        with pytest.raises(ValueError):
            await client.analyze_image(image_path)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# MultiModelVisionScraper — skips already-done (image_path, model) pairs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_model_scraper_skips_completed_pairs(
    tmp_path: Path, png_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    images_dir = tmp_path / "data" / "images" / "2024" / "01" / "01"
    images_dir.mkdir(parents=True)
    (images_dir / "slug1-main.png").write_bytes(png_bytes)

    source_csv = tmp_path / "gt.csv"
    source_csv.write_text(
        "url,slug,date,page_title\n"
        "https://www.smbc-comics.com/comic/slug1,slug1,2024-01-01,Slug1\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    variants_csv = output_dir / "smbc_vision_variants.csv"

    # Pre-populate: slug1-main.png already done for model-a
    rel_path = str(Path("images") / "2024" / "01" / "01" / "slug1-main.png")
    existing_row = _make_variant("slug1", "main", "model-a", rel_path)
    append_vision_rows([existing_row], variants_csv)

    call_count = 0

    async def fake_post(url: str, json: dict):
        nonlocal call_count
        call_count += 1
        return DummyResponse({
            "choices": [{"message": {"content": (
                "OCR_TEXT:\nNew text\n"
                "SHORT_DESCRIPTION:\nNew.\n"
                "ACCESSIBILITY_DESCRIPTION:\nNew scene.\n"
            )}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    scraper = MultiModelVisionScraper(
        api_key="test-key",
        models=["model-a", "model-b"],
        output_dir=output_dir,
        data_dir=tmp_path / "data",
        source_csv_path=source_csv,
        output_name="smbc_vision_variants",
    )

    # Patch all clients created inside the scraper
    original_init = OpenRouterVisionClient.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        monkeypatch.setattr(self.client, "post", fake_post)

    monkeypatch.setattr(OpenRouterVisionClient, "__init__", patched_init)

    results = await scraper.scrape()

    # model-a: slug1-main already done → 0 calls
    # model-b: slug1-main not done → 1 call
    assert call_count == 1
    assert len(results) == 1
    assert results[0].model == "model-b"
