from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from smbc_scraper.sources.openrouter_vision import (
    OpenRouterVisionClient,
    build_image_work_items,
    encode_image_as_data_url,
    parse_json_response,
)


class DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00"
        b"\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_parse_json_response_accepts_fenced_json() -> None:
    result = parse_json_response(
        """```json
        {
          "ocr_text": "HELLO",
          "short_description": "A test image.",
          "accessibility_description": "A tiny image used for testing."
        }
        ```"""
    )

    assert result.ocr_text == "HELLO"
    assert result.short_description == "A test image."


def test_build_image_work_items_joins_metadata_and_skips_completed(
    tmp_path: Path, png_bytes: bytes
) -> None:
    data_dir = tmp_path / "data"
    images_dir = data_dir / "images" / "2024" / "09" / "01"
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
        images_dir.parent.parent.parent,
        source_csv,
        existing_output,
    )

    assert len(items) == 1
    assert items[0].slug == "critical"
    assert items[0].image_kind == "main"
    assert items[0].comic_url == "https://www.smbc-comics.com/comic/critical"
    assert items[0].comic_date == date(2024, 9, 1)
    assert items[0].page_title == "Critical"


def test_encode_image_as_data_url_uses_image_mime_type(
    tmp_path: Path, png_bytes: bytes
) -> None:
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)

    data_url = encode_image_as_data_url(image_path)

    assert data_url.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_openrouter_client_parses_usage_and_response(
    tmp_path: Path, png_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(png_bytes)
    client = OpenRouterVisionClient(api_key="test-key")

    captured: dict = {}

    async def fake_post(url: str, json: dict):
        captured["url"] = url
        captured["json"] = json
        return DummyResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"ocr_text":"TEXT","short_description":"Short.",'
                                '"accessibility_description":"Longer."}'
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "total_tokens": 168,
                },
            }
        )

    monkeypatch.setattr(client.client, "post", fake_post)
    try:
        result = await client.analyze_image(image_path)
    finally:
        await client.close()

    assert captured["url"] == "/chat/completions"
    assert captured["json"]["model"]
    assert result.ocr_text == "TEXT"
    assert result.short_description == "Short."
    assert result.accessibility_description == "Longer."
    assert result.prompt_tokens == 123
    assert result.total_tokens == 168
