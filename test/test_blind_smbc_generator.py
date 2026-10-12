from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_generator_module():
    module_path = Path(__file__).resolve().parents[1] / "blind_smbc" / "generator.py"
    spec = importlib.util.spec_from_file_location("blind_smbc_generator", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load generator module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_data_prefers_stageplay_and_preserves_diagnostics(tmp_path) -> None:
    generator = _load_generator_module()

    base_csv = tmp_path / "smbc_ground_truth.csv"
    base_csv.write_text(
        "slug,date,comic_text,hover_text,votey_text\n"
        "whoopsie,2024-01-01,,hover,\n",
        encoding="utf-8",
    )

    variants_csv = tmp_path / "smbc_vision_variants.csv"
    variants_csv.write_text(
        "slug,image_kind,accessibility_description,ocr_text\n"
        "whoopsie,main,Raw description,RAW OCR\n",
        encoding="utf-8",
    )

    stageplay_csv = tmp_path / "smbc_vision_stageplay.csv"
    stageplay_csv.write_text(
        (
            "slug,image_kind,stageplay_script,diagnostic_ocr_text,"
            "diagnostic_accessibility_description\n"
            "whoopsie,main,\"Panel 1.\nROBOT: Hello.\","
            "\"CLEAN OCR\",\"Clean description\"\n"
        ),
        encoding="utf-8",
    )

    generator.DATA_PATH_OUT = base_csv
    generator.DATA_PATH_GOLD = tmp_path / "unused.csv"
    generator.VARIANTS_PATH = variants_csv
    generator.STAGEPLAY_PATH = stageplay_csv

    df = generator.load_data()
    row = df.iloc[0]

    assert row["comic_text"].replace("\r\n", "\n") == "Panel 1.\nROBOT: Hello."
    assert row["diagnostic_ocr_text"] == "CLEAN OCR"
    assert row["diagnostic_accessibility_description"] == "Clean description"
    assert row["text_diagnostics_url"] == "/text-diagnostics/whoopsie.html"
