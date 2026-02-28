# AccessPDF

Make PDFs accessible. Fixes structure, reading order, tables, and headings automatically -- then helps you add image descriptions with local AI or by hand.

Targets **WCAG 2.1 AA** and **PDF/UA**.

## Quick start

```bash
pip install "accesspdf[web]"
accesspdf serve
```

This opens a browser UI at `http://localhost:8080`. Upload a PDF, get an accessibility report, download the fixed version. If your PDF has images, you can write alt text right in the browser -- or let AI do a first draft.

For AI-generated alt text, we recommend **[Ollama](https://ollama.com)** -- it's free, runs locally, and needs no API key. Install it, then:

```bash
ollama pull llava
```

That's it. Select "Ollama" in the web UI and click generate.

---

## How it works

AccessPDF does two things:

1. **Fixes structure automatically** -- tags, language, reading order, headings, tables, links, bookmarks
2. **Helps you add image descriptions** -- the one part that needs a human (or AI + human review)

Your original PDF is never modified. Output always goes to a new file.

## CLI workflow

If you prefer the command line over the web UI:

```bash
# 1. See what's wrong (read-only, never touches your file)
accesspdf check my-document.pdf

# 2. Fix structural issues
accesspdf fix my-document.pdf -o my-document_accessible.pdf

# 3. Generate AI alt text drafts (optional)
accesspdf generate-alt-text my-document_accessible.pdf

# 4. Review and approve the drafts
accesspdf review my-document_accessible.pdf

# 5. Re-run fix to inject approved descriptions
accesspdf fix my-document.pdf -o my-document_accessible.pdf --alt-text my-document.alttext.yaml
```

## AI alt text providers

AccessPDF uses AI vision models to draft image descriptions. You always review before anything gets injected.

| Provider | Setup | API key? | Cost |
|----------|-------|----------|------|
| **Ollama** (recommended) | [Install Ollama](https://ollama.com), `ollama pull llava` | No | Free (local) |
| Google Gemini | None | `GOOGLE_API_KEY` | Free tier |
| Anthropic (Claude) | `pip install accesspdf[anthropic]` | `ANTHROPIC_API_KEY` | Paid |
| OpenAI (GPT-4) | `pip install accesspdf[openai]` | `OPENAI_API_KEY` | Paid |

**Ollama is the easiest** -- no API key, no account, nothing leaves your machine. Just install it and pull a model.

For cloud providers, set your key as an environment variable or pass it directly:

```bash
accesspdf generate-alt-text my-document.pdf --provider gemini --api-key AIza...
```

In the web UI, you can paste your API key in the settings panel -- it's sent per-request and never saved to disk.

## Batch processing

Fix every PDF in a folder:

```bash
accesspdf batch ./papers/ -o ./papers/accessible/
accesspdf batch ./papers/ -o ./papers/accessible/ -r   # include subdirectories
```

## The sidecar file

Image descriptions live in a `.alttext.yaml` file next to your PDF:

```yaml
images:
- id: img_37044c
  page: 1
  ai_draft: 'Bar chart showing quarterly revenue from 2023-2025.'
  alt_text: 'Bar chart showing quarterly revenue. Q1 2025 is highest at $4.2M.'
  status: approved
```

Statuses: **needs_review** (not yet described), **approved** (gets injected), **decorative** (screen readers skip it). You can edit this file by hand.

## CLI reference

```
accesspdf check <pdf>                    # Analyze accessibility (read-only)
accesspdf fix <pdf> -o <output>          # Fix structure + inject alt text
accesspdf fix <pdf> --alt-text <yaml>    # Fix with sidecar descriptions
accesspdf batch <dir> -o <outdir>        # Fix all PDFs in a directory
accesspdf review <pdf>                   # Terminal UI for alt text
accesspdf serve                          # Web UI at localhost:8080
accesspdf generate-alt-text <pdf>        # AI drafts (Ollama default)
accesspdf providers                      # Show available AI providers
```

## Installation options

```bash
pip install accesspdf          # CLI only
pip install "accesspdf[web]"   # CLI + browser UI (recommended)
pip install "accesspdf[anthropic]"  # Add Claude provider
pip install "accesspdf[openai]"     # Add GPT-4 provider
```

## Contributing

```bash
git clone https://github.com/laurenaulet/accesspdf.git
cd accesspdf
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

Apache 2.0
