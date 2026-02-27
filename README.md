# AccessPDF

Open-source Python CLI tool for PDF accessibility remediation. Fixes structural issues (tags, metadata, headings, reading order, tables, links, bookmarks), provides a workflow for adding alt text to images, and optionally uses AI to draft image descriptions.

Targets **WCAG 2.1 AA** and **PDF/UA** compliance.

## Installation

```bash
pip install accesspdf
```

Optional extras:

```bash
# Web UI for browser-based review
pip install accesspdf[web]

# AI providers (pick one or all)
pip install accesspdf[anthropic]
pip install accesspdf[openai]
pip install accesspdf[gemini]
pip install accesspdf[all-providers]
```

## Quick Start

```bash
# 1. Check a PDF for accessibility issues
accesspdf check thesis.pdf

# 2. Fix structural problems (tags, metadata, headings, tables, links, bookmarks)
accesspdf fix thesis.pdf -o thesis_accessible.pdf

# 3. Review and write alt text for images (terminal UI)
accesspdf review thesis_accessible.pdf

# 4. Or generate AI drafts first, then review
accesspdf generate-alt-text thesis_accessible.pdf --provider ollama
accesspdf review thesis_accessible.pdf

# 5. Re-run fix to inject approved alt text
accesspdf fix thesis.pdf -o thesis_accessible.pdf --alt-text thesis.alttext.yaml
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `accesspdf check <pdf>` | Analyze a PDF for accessibility issues (read-only) |
| `accesspdf fix <pdf>` | Apply structural fixes and optionally inject alt text |
| `accesspdf batch <dir>` | Fix all PDFs in a directory at once |
| `accesspdf review <pdf>` | Open terminal UI to review and approve alt text |
| `accesspdf serve` | Start web UI for browser-based review |
| `accesspdf generate-alt-text <pdf>` | Generate AI alt text drafts |
| `accesspdf providers` | Show available AI providers and their status |

## What Gets Fixed

- **Tags** -- adds document structure tree if missing (Document, P, Span elements)
- **Metadata** -- sets document title and language
- **Headings** -- detects heading hierarchy from font sizes and creates H1-H6 tags
- **Reading order** -- analyzes text layout to set logical reading sequence
- **Tables** -- detects ruled tables and creates Table/TR/TH/TD structure with scope and header references
- **Links** -- tags hyperlink annotations with /Link structure elements
- **Bookmarks** -- creates bookmark outlines from heading structure
- **Alt text** -- injects approved image descriptions from sidecar files

## What Gets Checked

The `check` command reports issues across several WCAG criteria:

- **Tagged PDF** -- whether the document has a structure tree
- **Document language** -- whether `/Lang` is set
- **Document title** -- whether title metadata exists
- **Image alt text** -- images without descriptions
- **Link text quality** -- ambiguous ("click here"), bare URLs, or empty link text
- **Table headers** -- tables missing TH cells
- **Text contrast** -- text colors that may not meet WCAG AA contrast ratios (4.5:1)

## Web UI

Start the browser-based review interface:

```bash
accesspdf serve --port 8080
```

Upload a PDF, review images, write or edit alt text, then download the fixed PDF. The web UI includes an AI mode toggle -- pick a provider (Ollama is free and local), paste an API key for cloud providers, and generate drafts with one click.

## AI Providers

AccessPDF supports multiple vision AI providers for generating alt text drafts. Drafts always require human review before injection.

| Provider | Default Model | API Key Required |
|----------|---------------|------------------|
| **Ollama** (default) | llava:13b | No -- runs locally |
| Anthropic | claude-sonnet-4-20250514 | Yes (`ANTHROPIC_API_KEY`) |
| OpenAI | gpt-4o | Yes (`OPENAI_API_KEY`) |
| Gemini | gemini-2.0-flash | Yes (`GOOGLE_API_KEY`) |

API keys can be set as environment variables or pasted directly in the web UI (never saved to disk).

```bash
# Check which providers are available
accesspdf providers

# Generate drafts with the default (Ollama)
accesspdf generate-alt-text thesis_accessible.pdf

# Or use a cloud provider
accesspdf generate-alt-text thesis_accessible.pdf --provider anthropic
```

## How It Works

1. **Never modifies the original PDF** -- all output goes to a separate file
2. **Sidecar files** (`.alttext.yaml`) store image descriptions separately, keyed by content hash
3. **AI drafts need human approval** -- generated text gets `status: needs_review` until you approve it
4. **Processors run independently** -- if one fails, the others still apply their fixes
5. **Idempotent** -- running `fix` twice produces the same result

## Contributing

```bash
git clone https://github.com/laurenaulet/accesspdf.git
cd accesspdf
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

Apache 2.0
