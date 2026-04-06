# Multi-LLM Vision Pipeline Spec

## Current State Assessment

### What works today

| Capability | Status | Notes |
|---|---|---|
| OCR pass (single model) | ✓ Works | `ocr` subcommand via OpenRouter |
| "Describe the comic" pass | ✓ Works | Same pass — `ocr_text`, `short_description`, `accessibility_description` in one shot |
| Restartable (skip already-done) | ✓ Works | `load_completed_image_paths` skips rows by `image_path` in existing output CSV |
| Multiple LLMs without overwriting | ✗ Missing | `--output-name` lets you write to different files, but there's no unified DB that holds all model results side-by-side |
| Gold/synthesis pass | ✗ Missing | No command to aggregate OCR + description variants and submit to a final LLM |

### The core gap

The current `ocr` command writes one flat CSV per run: `smbc_openrouter_vision.csv`. Each row is `(slug, image_kind, model, ocr_text, short_description, accessibility_description)`. If you run it with two models you get two CSVs. There is no merge step and no gold synthesis step.

---

## Design

### Principle: keep it simple and shippable today

- One new subcommand: **`ocr-multi`** — runs OCR across N models and writes a merged "variants" CSV.
- One new subcommand: **`ocr-gold`** — reads the variants CSV and submits each comic to a final LLM to pick/synthesise the best OCR and description.
- Both are restartable: they check for already-completed rows before doing any API work.
- No new DB layer required — flat CSVs are the storage format, consistent with the rest of the project.

---

## Data model additions (`models.py` / `openrouter_vision.py`)

### `VisionVariantRow` (new)

Stored in `out/smbc_vision_variants.csv`.

```
slug, image_kind, image_path, comic_url, date, page_title,
provider, model,
ocr_text, short_description, accessibility_description,
prompt_tokens, completion_tokens, total_tokens
```

This is identical to `VisionAnalysisRow` — the existing model is reused.
The output filename is the only difference: `smbc_vision_variants` instead of `smbc_openrouter_vision`.

### `GoldRow` (new)

Stored in `out/smbc_vision_gold.csv`.

```
slug, image_kind, image_path, comic_url, date, page_title,
gold_ocr_text, gold_short_description, gold_accessibility_description,
models_used,
prompt_tokens, completion_tokens, total_tokens
```

- `models_used`: comma-joined list of model IDs that contributed variants.
- Gold fields are produced by the synthesis LLM.

---

## New CLI subcommands

### `ocr-multi`

```
smbc-scrape ocr-multi
  --models MODEL [MODEL ...]     # one or more openrouter model IDs
  --source-csv PATH              # metadata CSV (default: out/smbc_ground_truth.csv)
  --output-name STR              # base filename (default: smbc_vision_variants)
  --limit INT                    # cap total images per model run
  --concurrency INT              # parallel requests per model (default: 1)
  --overwrite                    # reprocess already-done images
```

**Behaviour:**

1. For each model in `--models`, run the same vision pipeline as `ocr`.
2. Restartability: load `out/<output-name>.csv` at startup; skip `(image_path, model)` pairs already present.
3. Append new rows to the variants CSV after each model completes.
4. The output CSV grows monotonically — multiple runs with different `--models` safely accumulate.

### `ocr-gold`

```
smbc-scrape ocr-gold
  --variants-csv PATH            # input (default: out/smbc_vision_variants.csv)
  --model MODEL                  # synthesis model (default: google/gemini-2.5-flash-lite)
  --source-csv PATH              # metadata CSV (default: out/smbc_ground_truth.csv)
  --output-name STR              # base filename (default: smbc_vision_gold)
  --limit INT
  --concurrency INT              # default: 1
  --overwrite
```

**Behaviour:**

1. Load variants CSV. Group by `(slug, image_kind)`.
2. Load gold output CSV at startup; skip `(slug, image_kind)` pairs already present (restartable).
3. For each `(slug, image_kind)` group, build a synthesis prompt containing all variant OCR and descriptions, then call the synthesis model.
4. Write gold rows to `out/smbc_vision_gold.csv`.

**Synthesis prompt (per comic image):**

```
You are producing the best possible accessibility record for a single comic image.
You have been given OCR and description results from multiple AI models.
Synthesise the most accurate and complete version of each field.

Return a single JSON object with exactly these keys:
- gold_ocr_text: best OCR of the visible text
- gold_short_description: one concise sentence
- gold_accessibility_description: detailed scene description for a blind reader

Variants:
<MODEL: google/gemini-2.5-flash-lite>
ocr_text: ...
short_description: ...
accessibility_description: ...

<MODEL: anthropic/claude-3.5-sonnet>
...

Rules: output JSON only. Do not use markdown fences.
```

---

## Restartability guarantees

| Command | Resume key | How |
|---|---|---|
| `ocr` | `image_path` | `load_completed_image_paths` already does this |
| `ocr-multi` | `(image_path, model)` | Load variants CSV at startup, build set of done pairs |
| `ocr-gold` | `(slug, image_kind)` | Load gold CSV at startup, build set of done pairs |

All three commands: if interrupted, re-run and they pick up exactly where they left off.

---

## File layout

```
out/
  smbc_ground_truth.csv            # comic metadata (existing)
  smbc_openrouter_vision.csv       # legacy single-model ocr output (existing)
  smbc_vision_variants.csv         # all model variants (new, grows with each run)
  smbc_vision_gold.csv             # gold synthesis (new)
```

No schema changes to `ComicRow` or `VisionAnalysisRow` are needed.

---

## Implementation plan

1. **`openrouter_vision.py`**: add `load_completed_variant_pairs()` (returns `set[tuple[str,str]]` of done `(image_path, model)`), `save_vision_rows_append()` (CSV append mode), `GoldRow` model, `GoldPrompt` builder, `GoldSynthesiser` class.
2. **`cli.py`**: add `run_ocr_multi()` and `run_ocr_gold()` handlers; register `ocr-multi` and `ocr-gold` subparsers.
3. **`Makefile`**: add `ocr-multi` and `ocr-gold` targets.

---

## What is explicitly NOT changing

- `VisionAnalysisRow` schema — reused as-is for variants.
- `ComicRow` / `models.py` — no changes.
- `export.py` — no changes.
- Existing `ocr` command — unchanged.
- Storage format stays flat CSV (no DB).
