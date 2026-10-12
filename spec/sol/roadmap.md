# SMBC data and accessibility roadmap

## Executive assessment

The repository is moving in the right direction, but the three product goals are
at different levels of completion.

| Goal | Status | Evidence | Main gap |
| --- | --- | --- | --- |
| Gather all SMBC comic data | Mostly met for official metadata and main images | The local official export has 7,564 unique comics with no duplicate rows. Raw/output storage contains roughly 15,000 files, and the scraper supports full, incremental, missing-ID, index-rebuild, and image-backfill workflows. | There is no automated completeness manifest proving that metadata, main image, bonus image, hover text, and source HTML exist for every expected comic. The current vision dataset contains only `main` images. |
| Produce data-science-ready data | Partially met | Stable CSV/XLSX exports, Pydantic models, deterministic sorting, source labels, image-level vision rows, token counts, and model provenance exist. The local vision file has 7,506 unique comic rows; 7,377 have OCR, 7,396 have short descriptions, and 7,381 have accessibility descriptions. | There is no canonical comic-level analytical table, explicit schema/version contract, Parquet dependency, dataset manifest, validation report, splits, quality/confidence labels, or reproducible lineage from raw inputs through generated records. |
| Publish “SMBC for the Blind” | Prototype only | A static Jinja site generator, accessible landmarks, skip link, comic navigation, diagnostics page, hover text, and bonus-text sections exist. Stageplay synthesis code and tests also exist. | The generated site is not integrated into the CLI, omits the specified archive/feed/sitemap deliverables, filters out comics with no transcript, depends on a single selected representation, and has no produced stageplay output in `out`. Search requires JavaScript and the generator's incremental mode can leave stale pages after data/template changes. |
| Preserve old data and resume safely | Partially met | Metadata updates merge existing rows, OCR/synthesis outputs skip completed keys, image downloads skip existing files, and an incremental legacy-ID state file is maintained. Vision writes are append-oriented, so successful calls survive later failures. | Writes are not crash-atomic, appends are not locked, state and data are not committed as one transaction, `--overwrite` semantics can create duplicates rather than replace a key, full/range commands can replace a prior export with a partial result, and there is no snapshot/rollback or run manifest. |

The strongest part is acquisition. The next architectural step should be to stop
treating “the description” as one field. A comic has several complementary,
versioned representations, and the website should let the reader choose among
them without discarding any.

## Product direction inferred from the code

The application is becoming a durable, provenance-aware SMBC corpus builder
with two consumers:

1. reproducible research datasets; and
2. an accessibility-first static reading site.

The intended pipeline is:

`official pages and images -> immutable raw archive -> normalized comic/image records -> model-produced representation variants -> reviewed/published corpus -> static accessible site`

The current code implements pieces of every stage, but it lacks a single
pipeline contract connecting them and a release-quality “published corpus”
boundary.

## Target data contract

Keep factual extraction separate from presentation. The normalized corpus
should use at least these entities.

### `comic`

One row per canonical comic: stable comic ID, slug, legacy ID, canonical URL,
publication date, title, hover text, source timestamps, and previous/next IDs.

### `asset`

One row per downloaded object: comic ID, kind (`main`, `votey`, `html`), source
URL, relative path, byte size, MIME type, SHA-256, HTTP metadata, retrieval time,
and validation status.

### `representation`

One row per way of rendering an asset or whole comic. Required fields:

- `comic_id`, optional `asset_id`, and `image_kind`;
- `representation_type`: `verbatim_ocr`, `concise_dialogue`, `stageplay`,
  `literal_accessibility`, or `interpretive_accessibility`;
- `content`, `language`, `schema_version`, and `prompt_version`;
- provider, model, generation parameters, generated timestamp, and token/cost data;
- source representation IDs used for synthesis;
- quality status (`unreviewed`, `accepted`, `needs_review`, `rejected`), confidence,
  validation flags, and optional human correction provenance.

These forms should coexist. The site can default to `stageplay` or
`literal_accessibility`, while exposing “Dialogue only,” “Stageplay,” “Detailed
visual description,” and “Raw OCR” as separate headings or reader preferences.
Do not synthesize them into a single destructive “best text” column.

### `dataset_release`

A manifest for each publishable build: release ID, schema versions, git commit,
prompt hashes, source file hashes, row/asset counts, missingness statistics,
validation results, and generated artifact hashes.

The primary research delivery should be Parquet tables plus CSV compatibility
exports and a data dictionary. Keep newline-rich representation content in a
long table rather than adding one new wide column per prompt experiment.

## Safety requirements

The following are release blockers because the project explicitly promises
resume safety and preservation of previous work.

- Write every replacement to a sibling temporary file, flush and validate it,
  then atomically replace the destination.
- Before a destructive or `--overwrite` run, create a timestamped snapshot or
  content-addressed backup and print the recovery path.
- Never advance incremental state until the corresponding metadata and asset
  writes are durable. State must record the last attempted ID, last successful
  ID, gaps, and run ID rather than only one integer.
- Make generated rows idempotent by a declared primary key. For representations,
  include comic/asset, representation type, model, and prompt version. A rerun
  should skip or deliberately supersede that key, never silently duplicate it.
- Add a lock per output dataset so concurrent processes cannot interleave CSV
  records or race on headers.
- Treat raw HTML and images as immutable. If upstream bytes change, store a new
  content hash/version and retain the prior object.
- Validate counts, uniqueness, parseability, foreign keys, hashes, and expected
  coverage before promoting a staged dataset or site build.
- Make full/range scraping merge by default. Require an explicit, loudly named
  option to create a replacement corpus.

## Sprint 1 — Make the corpus durable and measurable

**Outcome:** every run can resume safely, cannot silently shrink the corpus, and
produces a machine-readable coverage report.

### Work

1. Add shared atomic writers for JSON, CSV, XLSX, and Parquet; add output locking
   and timestamped backups for replacements.
2. Change `smbc`, `smbc-all`, and rebuild flows to stage and merge by default.
   Couple state promotion to successful corpus validation.
3. Replace the one-integer state with a versioned run checkpoint containing run
   ID, bounds, successes, known missing IDs, errors, and timestamps. Migrate the
   existing state file safely.
4. Inventory all expected comics and assets. Emit `coverage.json` and
   `coverage.csv` with metadata/main/votey/HTML status, hashes, missing fields,
   and unexpected duplicates.
5. Add recovery and failure-injection tests: interrupted writes, malformed prior
   CSV, duplicate append, concurrent append, stale state, partial range, and
   missing/corrupt images.
6. Document backup, resume, repair, and deliberate replacement procedures.

### Acceptance criteria

- Killing a run during any write leaves either the previous valid artifact or
  the new valid artifact, never a truncated file.
- A range scrape cannot reduce the number of previously known comics by default.
- Repeating an identical run produces no duplicate logical records.
- Coverage reports reconcile expected comic IDs with local HTML, main images,
  votey images, and metadata, and exit nonzero when configured thresholds fail.
- Tests demonstrate restoration from the latest snapshot.

## Sprint 2 — Publish a versioned, multi-representation research dataset

**Outcome:** the corpus is directly usable for data science and supports several
honest descriptions of the same comic without choosing one prematurely.

### Work

1. Implement the `comic`, `asset`, `representation`, and `dataset_release`
   schemas with explicit primary/foreign keys and schema versions.
2. Add prompt templates and parsers for four first-class outputs:
   `verbatim_ocr`, `concise_dialogue`, `stageplay`, and
   `literal_accessibility`. Keep interpretive joke explanation separate and
   optional.
3. Version prompts in files, hash them into every row, preserve raw model
   responses, and record model parameters and lineage. Replace fragile labeled
   text parsing with validated structured output where supported, retaining a
   fallback parser.
4. Run representation generation for both main and votey assets. Do not infer
   absence of a votey merely because the current variants file lacks it.
5. Add automatic quality checks for empty/trivial OCR, hallucinated dialogue,
   missing panels/speakers, disagreement across variants, and suspiciously
   duplicated model output. Create a stratified human-review sample emphasizing
   diagrams, charts, equations, silent comics, and bonus-dependent jokes.
6. Export normalized Parquet and CSV tables, a data dictionary, deterministic
   train/validation/test splits, a manifest, and summary statistics.

### Acceptance criteria

- Every representation is traceable to asset hash, prompt version, model, and
  source representations.
- At least the four representation types can coexist for one comic and are
  independently reviewable/correctable.
- Main and votey coverage and quality metrics are reported independently.
- A clean build from immutable raw inputs recreates the same normalized tables
  except for explicitly recorded nondeterministic model outputs.
- The release validator rejects duplicate keys, orphan records, invalid dates,
  missing hashes, and unparseable content.

## Sprint 3 — Ship the blind-reader site from the published corpus

**Outcome:** a complete, static, accessibility-tested site is generated from a
validated dataset release and can be updated without stale pages.

### Work

1. Move the site generator behind the main CLI with explicit input release,
   output directory, base URL, clean/staged build, and incremental options.
2. Render every comic, including records whose generated descriptions are
   missing. Show explicit data-quality notices instead of filtering comics out.
3. Give readers separate, clearly labeled sections for dialogue-only,
   stageplay, detailed visual description, raw OCR, hover text, and bonus panel.
   Label machine-generated and human-reviewed content.
4. Complete the specified static outputs: chronological archive/year pages,
   stable previous/next links with descriptive labels, `latest.txt`,
   `latest.json`, sitemap, robots file, and a no-JavaScript browse/search
   fallback. JavaScript search may remain an enhancement.
5. Build into a temporary site directory, validate all internal links and page
   invariants, then atomically promote the whole site. Track input manifest and
   template hashes so incremental builds invalidate all affected pages.
6. Add automated accessibility and HTML checks plus manual keyboard,
   screen-reader, CSS-disabled, image-disabled, narrow viewport, and text-browser
   QA. Test representative diagram, multi-speaker, silent, and votey-dependent
   comics with blind-reader feedback if available.

### Acceptance criteria

- The number of comic pages equals the validated comic count; missing generated
  text never removes a comic from the archive.
- The site works as a useful reader with JavaScript and images disabled.
- Every page has one `h1`, valid heading order, landmarks, skip navigation,
  descriptive link text, provenance/quality labels, and resolving internal links.
- Template or source-data changes cannot leave stale comic pages.
- A failed build never replaces the last known-good deployed directory.

## Recommended sequencing and release gates

Do not spend a full-corpus model budget until Sprint 1's idempotency, manifest,
and recovery gates pass. In Sprint 2, validate prompts on a small, deliberately
difficult gold set before scaling. Treat Sprint 3 as a consumer of a named
dataset release, not as another ad hoc CSV merge.

The practical definition of done is not “the scraper ran.” It is: a manifest can
prove what was collected, every transformation is reproducible and non-destructive,
multiple accessibility representations are preserved, and the published site
exposes them predictably for every known comic.
