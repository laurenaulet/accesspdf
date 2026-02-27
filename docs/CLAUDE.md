# AccessPDF — Claude Code Briefing

## What This Project Is

AccessPDF is an open-source Python CLI tool and library that remediates PDF files for
accessibility compliance (WCAG 2.1 AA / PDF/UA). It fixes structural issues automatically
and provides a workflow for adding alt text to images — either manually, via a terminal UI
(TUI), or with optional AI assistance.

**The single most important design principle: no API key should ever be required.**
All structural fixes and the manual alt text workflow must work fully offline.
AI is an optional accelerant, not a dependency.

---

## Architecture in Brief

```
Input PDF
  → Analyzer          (reads structure, images, metadata → AnalysisResult)
  → Remediation Pipeline  (independent Processor classes, each fixing one concern)
  → AltText System    (sidecar YAML ↔ TUI review ↔ optional AI provider)
  → Writer            (injects approved alt text, writes output PDF — NEVER modifies original)
  → Reporter          (JSON + Markdown reports)
```

The **sidecar file** (`document.alttext.yaml`) is the source of truth for all alt text.
It is created on first run, holds every image with hash/page/caption/alt_text/status,
and is consumed by the Writer. AI drafts and manual edits both write to it.
Image IDs are content-hash-based so the sidecar survives PDF updates.

---

## Key Design Decisions (Don't Reverse These)

- **Never modify the original PDF.** All output goes to a separate path. Enforce this hard.
- **Sidecar-first.** Alt text is never injected without going through the sidecar. There is no
  shortcut that writes AI output directly to a PDF.
- **AI drafts require human approval.** `generate-alt-text` writes to sidecar with
  `status: needs_review`. Only `status: approved` entries get injected by the Writer.
- **Processor failures are non-fatal.** Each Processor runs in try/except. A failure adds a
  warning to the report and skips that fix — it never aborts the whole document.
- **Idempotent runs.** Running the tool twice on the same input produces identical output.
  Sidecar image IDs are md5(image_bytes) so they're stable.
- **Provider abstraction.** All vision AI flows through the `AltTextGenerator` protocol.
  Zero provider-specific code outside `accesspdf/providers/`. Adding a new provider means
  adding one file in that directory and one entry in the provider registry — nothing else changes.

---

## Module Structure

```
accesspdf/
  __init__.py
  cli.py                  # Typer app; all commands defined here
  analyzer.py             # PDFAnalyzer → AnalysisResult
  pipeline.py             # orchestrates processors
  processors/
    __init__.py
    base.py               # Processor protocol + ProcessorResult
    tagger.py
    metadata.py
    reading_order.py
    headings.py
    tables.py
    links.py
    bookmarks.py
  alttext/
    __init__.py
    sidecar.py            # SidecarFile, AltTextEntry, SidecarManager
    injector.py           # injects approved alt text into PDF via pikepdf
    cache.py              # SQLite cache keyed on md5+provider+model+prompt_hash
  providers/
    __init__.py
    base.py               # AltTextGenerator protocol, ImageContext, AltTextResult
    anthropic.py
    openai.py
    gemini.py
    ollama.py
    noop.py               # NoOpProvider — returns empty result, flags for review
  review/
    __init__.py
    app.py                # Textual TUI app
    widgets.py            # ImagePanel, AltTextEditor, StatusBar
    renderer.py           # terminal image rendering (sixel + block char fallback)
  reporter.py             # JSON + Markdown + HTML reports
  writer.py               # final PDF output
  config.py               # Pydantic config model + YAML loading
  models.py               # shared dataclasses: AnalysisResult, RemediationResult, etc.
```

---

## CLI Commands

```bash
accesspdf check <pdf>                          # analyze only, no modification
accesspdf fix <pdf> [--output <path>]          # structural fixes; creates sidecar
accesspdf fix <pdf> --alt-text <sidecar.yaml>  # inject approved alt text
accesspdf generate-alt-text <pdf> [--provider ollama|anthropic|openai|gemini]
accesspdf review <pdf>                         # open TUI
accesspdf batch <dir> [--output-dir <dir>]
accesspdf cost-estimate <dir>                  # cloud providers only
accesspdf providers                            # show provider availability
```

---

## Sidecar File Format

```yaml
document: thesis.pdf
generated: 2026-03-01T14:22:00Z
images:
  - id: img_a3f8c2          # md5 of image bytes (first 6 chars)
    page: 4
    hash: a3f8c2d901...     # full md5
    caption: "Figure 3.2: Mean reaction times"
    ai_draft: "Bar chart showing..."
    alt_text: ""            # blank = awaiting review
    status: needs_review    # needs_review | approved | decorative
  - id: img_b91d44
    page: 7
    hash: b91d44...
    caption: ""
    ai_draft: ""
    alt_text: "University logo"
    status: approved
```

---

## Provider Configuration

In `accesspdf.yaml`:
```yaml
ai:
  provider: ollama          # anthropic | openai | gemini | ollama | none
  model: llava:13b
  ollama_base_url: http://localhost:11434
  max_tokens: 300
```

API keys are loaded from environment variables ONLY — never from config files:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`

---

## Core Dependencies

| Package | Purpose |
|---|---|
| `pikepdf` | PDF structure manipulation, tag tree, alt text injection |
| `pdfminer.six` | Text/layout extraction, reading order analysis |
| `Pillow` | Image extraction and processing |
| `typer` | CLI |
| `pydantic` | Config and data model validation |
| `PyYAML` | Sidecar file read/write |
| `textual` | TUI review interface |
| `jinja2` | Report templates |
| `langdetect` | Auto-detect document language |
| `anthropic` | Anthropic provider (optional) |
| `openai` | OpenAI provider (optional) |
| `google-generativeai` | Gemini provider (optional) |
| `httpx` | Ollama provider HTTP calls |

---

## Test Commands

```bash
# Run all tests
hatch run test

# Run with coverage
hatch run test-cov

# Run a specific test file
hatch run pytest tests/test_sidecar.py -v

# Run offline only (skip any live API tests)
hatch run pytest -m "not live_api"

# Type checking
hatch run typecheck

# Linting
hatch run lint
```

---

## Test Corpus

Public-domain PDFs are in `tests/corpus/`:
- `simple.pdf` — single column, text only, no images
- `academic.pdf` — multi-column, images, citations
- `tables.pdf` — complex tables, mixed content
- `images.pdf` — image-heavy, various types (photos, charts, logos)

Generate synthetic test PDFs with `tests/fixtures/generate.py` (uses reportlab).

---

## Gotchas

- **pikepdf and pdfminer.six are both needed.** pikepdf for writing/tag manipulation,
  pdfminer for reading layout and text. Don't try to do everything with one.
- **PDF tag trees are fragile.** Always validate output with `tests/utils/validate.py`
  after any tag manipulation. A malformed tag tree can make a PDF worse than untagged.
- **Image extraction order is not page order.** Use pdfminer position data to associate
  images with their page location — don't rely on pikepdf's iteration order.
- **Ollama must be running before the provider is called.** The OllamaProvider should
  check connectivity at startup and raise a clear error if Ollama isn't reachable,
  not fail silently mid-batch.
- **Textual TUI tests run headless.** Use `textual run --dev` locally; in CI use
  Textual's `App.run_test()` harness.
- **Never use WidthType.PERCENTAGE in any docx output** — breaks in Google Docs.
  (Relevant if the reporter generates Word output in future.)

---

## What Good Alt Text Looks Like

This matters for prompt engineering and for evaluating output quality.

**Good:**
- "Bar chart showing mean reaction times across four conditions. Condition A is highest at 412ms, Condition D lowest at 287ms."
- "Scatter plot of temperature vs. pressure for 200 samples. Positive correlation, r=0.84."
- "Diagram of the mitochondrial electron transport chain showing Complexes I through IV."

**Bad:**
- "Image of a chart" (too vague)
- "A bar chart" (no data)
- "Figure 3" (just the label)
- "This image shows a bar chart that displays the mean reaction times for four different experimental conditions in the study." (too wordy, starts with 'This image shows')

**Decorative:** small icons, page dividers, background textures, purely aesthetic images
with no informational content. Mark these with `status: decorative` — they get tagged
as artifacts in the PDF so screen readers skip them.

---

## Phase Plan (from Roadmap)

- **Phase 0 (Weeks 1-2):** Foundation — repo, CI, data models, analyzer skeleton, sidecar R/W
- **Phase 1 (Weeks 3-7):** Structural remediation — all processors, fix/check commands, v0.1.0
- **Phase 2 (Weeks 8-10):** Manual alt text + TUI review — v0.2.0
- **Phase 3 (Weeks 11-14):** AI providers — v0.3.0
- **Phase 4 (Weeks 15-18):** Tables, links, contrast, polish — v1.0.0

Start with Phase 0. Don't skip ahead.
