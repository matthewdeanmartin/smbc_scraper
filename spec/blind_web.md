# SMBC for the Blind

## Goal

Build a static website that turns the scraped SMBC dataset into an accessibility-first, text-only reading experience.

The site should let a blind or low-vision user:

- get today's comic quickly
- understand the joke setup and punch line without needing the original image
- read OCR'd dialog and visible text in a clean order
- read bonus-panel / votey punch lines when present
- browse the archive efficiently with screen readers, keyboard-only navigation, text browsers, and high-latency / low-JS environments

This spec assumes the source data already exists, including:

- `out\smbc_ground_truth.csv`
- `out\smbc_openrouter_vision.csv` or an equivalent OCR/description export
- local image paths and metadata if needed for QA, but not for end-user rendering


## Product principles

### 1. Text-first, not image-first

The core experience should never require loading the comic image.

Users should be able to understand the comic from:

- title
- publication date
- short description
- accessibility description
- OCR text
- hover text
- votey / after-comic text


### 2. Zero-JS baseline

The website should work fully as static HTML and CSS.

JavaScript may be added later for optional enhancements, but the default architecture should assume:

- no client-side rendering
- no infinite scroll
- no hydration requirement
- no dynamic search requirement for the first version


### 3. Screen-reader predictability

Every page should have:

- one clear `h1`
- logical heading order
- skip links
- consistent landmarks
- stable navigation order
- no duplicate “read more” style labels
- explicit labels for every action


### 4. Respect old / specialized browsers

The site should be friendly to:

- screen readers over standard browsers
- text browsers
- browser reader modes
- high zoom users
- users who disable CSS
- users who navigate by headings, links, landmarks, and forms


### 5. “Today’s joke” should be first-class

The homepage should immediately answer:

- what is today’s comic?
- what happens in it?
- what text appears in it?
- what is the hover / bonus joke?


## Proposed output site

Suggested output folder:

- `site\`

Generated structure:

- `site\index.html`
- `site\archive\index.html`
- `site\comic\<slug>\index.html`
- `site\dates\YYYY\MM\DD\index.html` (optional redirect or duplicate canonical path only if useful)
- `site\feeds\latest.json`
- `site\feeds\latest.txt`
- `site\sitemap.xml`
- `site\robots.txt`
- `site\styles.css`

Preferred canonical comic URL pattern:

- `/comic/<slug>/`

This matches existing SMBC slug conventions and keeps links memorable.


## Core page types

## 1. Homepage

Purpose: deliver the newest comic with the least friction.

Sections, in order:

1. skip links
2. site title: `SMBC for the Blind`
3. one-sentence mission
4. “Today’s comic” block
5. direct links to previous / next / archive
6. optional short explanation of data quality

The “Today’s comic” block should include:

- comic title
- publication date
- canonical SMBC link
- short description
- accessibility description
- OCR text
- hover text
- votey / bonus text
- metadata notes if some fields are missing

Recommended reading order within the block:

1. title and date
2. short description
3. accessibility description
4. visible text / OCR
5. hover text
6. bonus / votey panel
7. original source link


## 2. Individual comic page

Purpose: best detailed reading experience for one comic.

Sections:

- breadcrumb
- title
- date
- nav to previous / next comic
- “Quick summary”
- “Detailed description”
- “Visible text”
- “Hover text”
- “Bonus panel”
- “Data notes”
- source links

Recommended section labels:

- `Quick summary`
- `Detailed description`
- `Visible text in the comic`
- `Hover text`
- `After-comic / bonus panel`
- `Source and metadata`

Important behavior:

- do not hide missing fields silently
- if OCR text is empty, say `No readable text detected.`
- if hover text is absent, say `No hover text captured.`
- if bonus panel is absent, say `No bonus panel text captured.`
- if the accessibility description is machine-generated, label it clearly


## 3. Archive page

Purpose: efficient browsing without requiring search.

Default archive format:

- reverse chronological list
- one row per comic
- title
- date
- one-sentence description
- link text that includes both title and date

Archive navigation options:

- latest first
- by year
- by month
- optional “random comic” link generated statically at build time

Do not make the first version depend on client-side filtering.


## 4. Plain-text feed outputs

Provide machine- and reader-friendly outputs:

- `latest.txt`: plain text version of the newest comic
- `latest.json`: latest comic metadata for external reuse

`latest.txt` should be intentionally simple so it works well with:

- terminal readers
- braille displays
- command-line fetch tools
- email mirroring or notification systems


## Data model for site generation

The generator should produce one normalized record per comic, not per image.

Suggested normalized fields:

- `slug`
- `date`
- `page_title`
- `comic_url`
- `source_url`
- `short_description`
- `accessibility_description`
- `ocr_text_main`
- `ocr_text_bonus`
- `hover_text`
- `votey_text`
- `image_path_main`
- `image_path_bonus`
- `has_bonus_panel`
- `data_quality_flags`
- `previous_slug`
- `next_slug`


## Input merge strategy

### Source 1: ground truth

From `smbc_ground_truth.csv`:

- slug
- date
- page title
- canonical comic URL
- hover text
- votey text

### Source 2: OCR / vision output

From the OpenRouter vision export:

- image kind (`main` or `votey`)
- OCR text
- short description
- accessibility description

### Merge rule

Collapse image-level rows into comic-level rows:

- `main` image contributes primary OCR and primary descriptions
- `votey` image contributes bonus OCR/description if present
- if `votey_text` exists in ground truth and OCR bonus text also exists, keep both
- prefer source fields that are explicitly comic metadata over guessed text

### Punch line handling

The punch line may be split across:

- OCR text in the main image
- hover text
- bonus / votey panel

So the generator should never try to reduce the joke to a single field.

Instead, expose all comedic surfaces distinctly:

- visible text joke
- hover joke
- bonus-panel joke


## Content design rules

### Separate “description” from “interpretation”

Avoid editorializing in the first version.

Use:

- `Quick summary` for a concise factual description
- `Detailed description` for a fuller accessible explanation

Do not add:

- “This joke means...”
- “The humor is that...”

unless that becomes a later optional feature.


### Preserve original text exactly when possible

For OCR fields:

- preserve line breaks where useful
- do not aggressively normalize punctuation
- keep uncertainty notes if the OCR pipeline emitted them


### Be explicit about machine-generated content

Add a short note such as:

`Descriptions and OCR are machine-generated from the comic image and may contain errors.`


## Accessibility requirements

### Required HTML structure

Every page should contain:

- `<a href="#main-content">Skip to main content</a>`
- `<header>`
- `<nav aria-label="Primary">`
- `<main id="main-content">`
- `<footer>`

Use headings in strict order:

- one `h1`
- `h2` for major sections
- `h3` only when needed inside a section


### Link text

Bad:

- `Read more`
- `Previous`
- `Next`

Better:

- `Previous comic: <title>`
- `Next comic: <title>`
- `Read comic: <title> (<date>)`


### CSS rules

Prefer:

- system fonts
- high contrast
- wide line height
- moderate measure
- visible focus states
- no motion dependence

Avoid:

- icon-only buttons
- low contrast metadata
- hover-only disclosure
- CSS that reorders content visually away from DOM order


### Browser friendliness

Pages should remain understandable if:

- CSS fails to load
- JS is disabled
- images are blocked
- only headings/links are navigated


## Static generation architecture

## Proposed implementation shape

Add a new generator module, for example:

- `smbc_scraper\site\blind_web.py`

Key responsibilities:

1. load and normalize merged comic data
2. compute previous / next relationships
3. emit HTML pages
4. emit archive pages
5. emit text/json feeds
6. emit supporting files (`sitemap.xml`, `robots.txt`, CSS)

Suggested internal functions:

- `load_blind_site_rows(...)`
- `merge_ground_truth_and_vision(...)`
- `build_comic_page_context(...)`
- `render_comic_page(...)`
- `render_homepage(...)`
- `render_archive_page(...)`
- `write_static_assets(...)`
- `build_blind_site(...)`

Use simple string templates or a very small templating engine.

Recommendation:

- use Jinja2 only if templating becomes repetitive
- otherwise keep generation dependency-light with built-in templates


## Update flow

### Full build

Use after:

- first dataset creation
- major template changes
- large OCR refreshes

Steps:

1. run `smbc-all` or otherwise produce fresh ground truth
2. run OCR / description enrichment
3. merge data
4. regenerate the entire static site
5. deploy the generated `site\` folder


### Incremental update

Use daily or whenever new SMBC comics appear.

Steps:

1. run `smbc-update`
2. run OCR/description only for new images
3. regenerate:
   - homepage
   - newest comic page
   - prior comic page if its `next` link changed
   - archive index pages affected by the new comic
   - `latest.txt`
   - `latest.json`
   - `sitemap.xml`
4. deploy only changed files if desired

Static site generation should still support a simple “regenerate everything” mode even if incremental output writing is later added.


## Deployment plan

Best initial deployment targets:

- GitHub Pages
- Netlify
- any static file host

Because the site is static:

- no database is required
- no backend is required
- no live app server is required

This is ideal for reliability and accessibility.


## Validation and QA plan

### Automated checks

Add generator checks for:

- every comic page has a title
- every comic page has a date or explicit undated marker
- all internal links resolve
- homepage points to the newest comic
- archive is reverse chronological
- no duplicate slugs


### Accessibility QA

Test with:

- keyboard-only navigation
- screen-reader landmark/headings flow
- browser with CSS disabled
- browser with images disabled
- narrow viewport

Check:

- reading order
- link clarity
- focus visibility
- no duplicate/confusing labels


### Content QA

Spot-check comics where humor depends on:

- hover text only
- bonus panel only
- chart/diagram layout
- OCR with multiple speakers
- very little visible text


## First release scope

Include:

- homepage with latest comic
- comic detail pages
- archive page
- previous/next navigation
- machine-generated description sections
- hover and bonus text sections
- latest text and JSON feeds

Do not require for v1:

- full-text search
- user accounts
- comments
- theme switching
- dynamic client-side filtering


## Suggested CLI integration

Eventually add a command such as:

- `uv run smbc-scrape blind-web --output-dir out --site-dir site`

Possible options:

- `--site-dir`
- `--ground-truth-csv`
- `--vision-csv`
- `--base-url`
- `--incremental`
- `--latest-only`


## Recommended implementation order

1. build merged comic-level dataset
2. build single-comic HTML template
3. build homepage from newest comic
4. build archive page
5. add latest text/json feeds
6. add sitemap and polish
7. add incremental rebuild support


## Open questions

- Should the homepage show only the latest comic or also a few recent comics?
- Should we expose the original image behind an explicit “show image” link, or keep the site fully text-only?
- Should machine-generated descriptions ever be human-editable overrides from a local correction file?
- Should there be a “low-confidence OCR” badge when OCR appears sparse or uncertain?


## Recommendation

Start with a deliberately boring static site:

- one clean CSS file
- no required JavaScript
- one page per comic
- one archive page
- one latest-text feed

If the text quality is good, that alone already delivers a meaningful “SMBC for the blind” experience and gives a strong base for later enhancements.
