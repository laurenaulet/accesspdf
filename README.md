# AccessPDF

A Python command-line tool that makes PDFs accessible. It fixes structural problems that prevent screen readers from understanding your document, and gives you a workflow for adding image descriptions (alt text) -- either manually or with AI assistance.

Targets **WCAG 2.1 AA** and **PDF/UA** compliance.

## Why does this matter?

PDFs are everywhere -- academic papers, government forms, reports. But most PDFs are inaccessible to people who use screen readers. Common problems include missing document structure (tags), no language set, tables without headers, and images without descriptions. AccessPDF fixes the structural issues automatically and helps you write the image descriptions.

## Installation

```bash
pip install accesspdf
```

This gives you the CLI tool and everything needed for structural fixes and manual alt text. For optional features:

```bash
# Browser-based UI for reviewing images and writing alt text
pip install accesspdf[web]

# AI-powered alt text drafts (pick your provider)
pip install accesspdf[anthropic]   # Claude
pip install accesspdf[openai]      # GPT-4
pip install accesspdf[gemini]      # Gemini
pip install accesspdf[all-providers]  # all of the above
```

## How to use it

### Step 1: Check your PDF

See what accessibility issues exist before changing anything. This is read-only -- it never touches your file.

```bash
accesspdf check my-document.pdf
```

You'll get a report like this:

```
  Accessibility Report: my-document.pdf
+--------------------------------------+
| Metric       | Value                 |
|--------------+-----------------------|
| Pages        | 12                    |
| Tagged       | No                    |
| Language set | No                    |
| Title        | Not set               |
| Images found | 5                     |
| Links found  | 0                     |
| Tables found | 0                     |
| Contrast     | OK                    |
| Errors       | 4                     |
| Warnings     | 1                     |
+--------------------------------------+

  X [tagged-pdf] PDF is not tagged. Screen readers cannot interpret the document structure.
  X [document-lang] Document language is not set.
  ! [document-title] Document title is not set in metadata.
  X [image-alt-text] 5 image(s) missing alt text.
```

### Step 2: Fix structural issues

This creates a new file with all the structural fixes applied. **Your original PDF is never modified.**

```bash
accesspdf fix my-document.pdf -o my-document_accessible.pdf
```

This automatically:
- Adds the tag structure tree (Document, paragraphs, spans)
- Sets the document language
- Detects headings from font sizes and creates H1-H6 tags
- Figures out reading order from the page layout
- Finds tables and creates Table/TR/TH/TD structure with header references
- Tags hyperlinks with /Link elements
- Creates a bookmark outline from headings

After fixing, a **sidecar file** (`my-document.alttext.yaml`) is created next to your PDF. This is where image descriptions live.

### Step 3: Add image descriptions

This is the part that needs a human. Every image in your PDF needs a description so screen readers can convey what the image shows. You have three options:

**Option A: Terminal UI**

```bash
accesspdf review my-document_accessible.pdf
```

This opens an interactive terminal app. You'll see each image, and you can type a description, mark it as approved, or mark decorative images (icons, dividers) so screen readers skip them.

**Option B: Web UI (browser)**

```bash
accesspdf serve
```

This opens a browser window at `http://localhost:8080`. Upload your fixed PDF, see all the images laid out, and type descriptions right in the browser. When you're done, download the final PDF.

**Option C: AI-assisted (fastest)**

Have AI draft descriptions, then you review and approve them:

```bash
# Generate drafts (uses Ollama by default -- free, runs locally)
accesspdf generate-alt-text my-document_accessible.pdf

# Then review and approve/edit the drafts
accesspdf review my-document_accessible.pdf
```

AI drafts are **never** injected automatically. They show up as suggestions that you approve, edit, or reject.

### Step 4: Inject the approved descriptions

Once you've written and approved all image descriptions, re-run `fix` with the sidecar file:

```bash
accesspdf fix my-document.pdf -o my-document_accessible.pdf --alt-text my-document.alttext.yaml
```

### Step 5: Verify

Run `check` again on the output to confirm everything is fixed:

```bash
accesspdf check my-document_accessible.pdf
```

## Processing many PDFs at once

Fix every PDF in a folder:

```bash
accesspdf batch ./papers/ -o ./papers/accessible/
```

This processes all PDFs and puts the fixed versions in the output directory. Add `-r` to include subdirectories.

If you have sidecar files with approved alt text ready:

```bash
accesspdf batch ./papers/ -o ./papers/accessible/ --alt-text-dir ./papers/
```

## AI providers for alt text

AccessPDF can use AI vision models to draft image descriptions. You still review everything before it gets injected.

| Provider | Runs locally? | API key needed? |
|----------|--------------|-----------------|
| **Ollama** (default) | Yes | No |
| Anthropic (Claude) | No | `ANTHROPIC_API_KEY` |
| OpenAI (GPT-4) | No | `OPENAI_API_KEY` |
| Gemini | No | `GOOGLE_API_KEY` |

**Ollama** is the default because it's free and runs on your machine. Install it from [ollama.com](https://ollama.com), then pull a vision model:

```bash
ollama pull llava:13b
```

For cloud providers, set your API key as an environment variable or pass it directly:

```bash
# Via environment variable
export ANTHROPIC_API_KEY=sk-ant-...
accesspdf generate-alt-text my-document_accessible.pdf --provider anthropic

# Or pass it directly
accesspdf generate-alt-text my-document_accessible.pdf --provider openai --api-key sk-...
```

In the web UI, you can paste your API key right in the browser -- it's sent per-request and never saved to disk.

Check which providers are available on your system:

```bash
accesspdf providers
```

## The sidecar file

Image descriptions are stored in a `.alttext.yaml` file next to your PDF. It looks like this:

```yaml
document: my-document.pdf
images:
- id: img_37044c
  page: 1
  hash: 37044c64001bee1d5ade98da9c1de419
  caption: ''
  ai_draft: 'Bar chart showing quarterly revenue from 2023-2025.'
  alt_text: 'Bar chart showing quarterly revenue. Q1 2025 is highest at $4.2M.'
  status: approved
- id: img_8527c6
  page: 3
  hash: 8527c67235abd6fa37d6dba179b12ad7
  caption: ''
  ai_draft: ''
  alt_text: ''
  status: decorative
```

Each image is identified by a hash of its content, so the sidecar stays valid even if you re-export the PDF. The `status` field controls what happens:

- **needs_review** -- not yet described, won't be injected
- **approved** -- the `alt_text` field gets injected into the PDF
- **decorative** -- marked as an artifact so screen readers skip it

You can edit this file by hand if you prefer.

## What does "accessible PDF" mean?

An accessible PDF has:

- **Tags** -- a structure tree telling screen readers what's a heading, paragraph, table, image, etc.
- **Language** -- so screen readers know how to pronounce the text
- **Reading order** -- so content is read in the right sequence, not left-to-right across columns
- **Alt text** -- descriptions of images for people who can't see them
- **Table headers** -- so screen readers can say "Name: Alice" instead of just "Alice"
- **Bookmarks** -- a navigation outline built from headings
- **Sufficient contrast** -- text dark enough to read against its background

AccessPDF checks for all of these and fixes everything it can automatically. Image descriptions are the one thing that requires human judgment.

## CLI reference

```
accesspdf check <pdf>                    # Analyze for issues (read-only)
accesspdf fix <pdf> -o <output>          # Fix structure + inject alt text
accesspdf fix <pdf> --alt-text <yaml>    # Fix and inject from sidecar
accesspdf batch <dir> -o <outdir>        # Fix all PDFs in a directory
accesspdf batch <dir> -r                 # Include subdirectories
accesspdf review <pdf>                   # Terminal UI for alt text
accesspdf serve                          # Web UI at localhost:8080
accesspdf serve -p 3000                  # Web UI on a different port
accesspdf generate-alt-text <pdf>        # AI drafts (Ollama default)
accesspdf generate-alt-text <pdf> -p anthropic  # Use Claude
accesspdf providers                      # Show available AI providers
accesspdf --version                      # Print version
```

## Contributing

```bash
git clone https://github.com/laurenaulet/accesspdf.git
cd accesspdf
pip install -e ".[dev]"
python -m pytest tests/ -v
```

152 tests. No real API calls in the test suite.

## License

Apache 2.0
