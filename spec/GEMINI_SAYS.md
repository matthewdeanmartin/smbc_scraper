# Spec: SMBC for the Blind (Static Site Generator)

## Goal
Create a fully textual, screen-reader-optimized static website for Saturday Morning Breakfast Cereal (SMBC) comics. The site prioritizes efficiency for blind users over visual aesthetics, while maintaining a clean, high-contrast interface for all.

## Core Principles
1. **Accessibility First**: Semantic HTML5, ARIA landmarks, and skip links are mandatory.
2. **Text-Centric**: Every comic must have a transcript, hover text, and votey description.
3. **Efficiency**: Screen reader users should be able to navigate the comic history and read transcripts with minimal keystrokes.
4. **Incremental Updates**: Only new or modified comics trigger page regeneration.

## Site Structure
- `/index.html`: The latest comic page.
- `/archive.html`: A chronological list of all comics, optimized for quick searching.
- `/comics/[slug].html`: Individual comic pages.
- `/about.html`: Information about the project and accessibility features.
- `/static/`: CSS and minimal assets.

## Data Schema
Based on the existing `ComicRow` model:
- `slug`: Unique identifier (e.g., `2025-09-13`).
- `date`: Publication date.
- `comic_text`: The full transcript.
- `hover_text`: The "title" attribute text from the image.
- `votey_text`: The bonus panel text/description.
- `description`: (Future) LLM-generated visual description of the panels.

## Technical Implementation (Prototype)
- **Language**: Python 3.10+
- **Templating**: Jinja2 for HTML generation.
- **Data Source**: CSV/Parquet exports from `smbc_scraper`.
- **Output**: Pure static HTML/CSS.

### Screen Reader Optimizations
- **Skip Links**: "Skip to Transcript", "Skip to Navigation".
- **Heading Hierarchy**:
  - `<h1>`: Site Title (Index) or Comic Title (Comic Page).
  - `<h2>`: Major sections (Transcript, Hover Text, Votey).
- **Navigation Shortcuts**: Logical `accesskey` attributes for Next (`n`), Previous (`p`), and Random (`r`).
- **Live Regions**: Use `aria-live` for dynamic content if any (though site is static).

## Development Phases
1. **Phase 1: Scaffolding**: Setup the generator and basic templates.
2. **Phase 2: Data Integration**: Import `gold_data` and map to templates.
3. **Phase 3: A11y Audit**: Test with screen readers (NVDA/VoiceOver) and adjust.
4. **Phase 4: Incremental Logic**: Implement checksum-based regeneration.
5. **Phase 5: Visual Polish**: High-contrast, responsive CSS.
