"""Generate synthetic test PDFs for processor testing using reportlab."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CORPUS_DIR = Path(__file__).parent.parent / "corpus"


def generate_all() -> dict[str, Path]:
    """Generate all test PDFs. Returns {name: path} dict."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "simple": generate_simple_pdf(CORPUS_DIR),
        "headings": generate_headings_pdf(CORPUS_DIR),
        "tables": generate_tables_pdf(CORPUS_DIR),
        "links": generate_links_pdf(CORPUS_DIR),
        "multicolumn": generate_multicolumn_pdf(CORPUS_DIR),
    }


def generate_simple_pdf(output_dir: Path) -> Path:
    """Single-column text-only PDF with several paragraphs."""
    path = output_dir / "simple.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("This is the first paragraph of a simple test document.", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(
            "The second paragraph contains more text to ensure we have enough content "
            "for the analyzer to work with. This paragraph is intentionally longer.",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            "A third paragraph rounds out this simple document. It contains only "
            "plain text with no images, tables, or links.",
            styles["Normal"],
        ),
    ]
    doc.build(story)
    return path


def generate_headings_pdf(output_dir: Path) -> Path:
    """PDF with varied font sizes mimicking heading hierarchy."""
    path = output_dir / "headings.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()

    h1_style = ParagraphStyle("H1", parent=styles["Normal"], fontSize=24, leading=28,
                               fontName="Helvetica-Bold", spaceAfter=12)
    h2_style = ParagraphStyle("H2", parent=styles["Normal"], fontSize=18, leading=22,
                               fontName="Helvetica-Bold", spaceAfter=10)
    h3_style = ParagraphStyle("H3", parent=styles["Normal"], fontSize=14, leading=18,
                               fontName="Helvetica-Bold", spaceAfter=8)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=12, leading=14,
                                 spaceAfter=6)

    story = [
        Paragraph("Document Main Title", h1_style),
        Paragraph("This is body text under the main title.", body_style),
        Spacer(1, 6),
        Paragraph("First Section", h2_style),
        Paragraph("Content of the first section with regular body text.", body_style),
        Spacer(1, 6),
        Paragraph("Subsection One Point One", h3_style),
        Paragraph("Details in this subsection.", body_style),
        Spacer(1, 6),
        Paragraph("Second Section", h2_style),
        Paragraph("Content of the second section.", body_style),
    ]
    doc.build(story)
    return path


def generate_tables_pdf(output_dir: Path) -> Path:
    """PDF with a simple table with headers and data rows."""
    path = output_dir / "tables.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()

    story = [
        Paragraph("Table Test Document", styles["Title"]),
        Spacer(1, 12),
        Paragraph("The following table shows sample data:", styles["Normal"]),
        Spacer(1, 12),
    ]

    data = [
        ["Name", "Age", "City"],
        ["Alice", "30", "New York"],
        ["Bob", "25", "San Francisco"],
        ["Carol", "35", "Chicago"],
    ]

    table = Table(data, colWidths=[2 * inch, 1.5 * inch, 2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Text after the table.", styles["Normal"]))

    doc.build(story)
    return path


def generate_links_pdf(output_dir: Path) -> Path:
    """PDF with hyperlinks embedded in text."""
    path = output_dir / "links.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()

    story = [
        Paragraph("Links Test Document", styles["Title"]),
        Spacer(1, 12),
        Paragraph(
            'Visit <a href="https://example.com">Example Website</a> for more info.',
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            'See also <a href="https://python.org">Python Homepage</a> '
            "for documentation.",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("This paragraph has no links.", styles["Normal"]),
    ]
    doc.build(story)
    return path


def generate_multicolumn_pdf(output_dir: Path) -> Path:
    """PDF simulating two-column layout with left and right text blocks."""
    path = output_dir / "multicolumn.pdf"

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    # Left column
    text_obj = c.beginText(72, height - 72)
    text_obj.setFont("Helvetica", 12)
    text_obj.textLine("Left column first line.")
    text_obj.textLine("Left column second line.")
    text_obj.textLine("Left column third line.")
    c.drawText(text_obj)

    # Right column
    text_obj = c.beginText(width / 2 + 36, height - 72)
    text_obj.setFont("Helvetica", 12)
    text_obj.textLine("Right column first line.")
    text_obj.textLine("Right column second line.")
    text_obj.textLine("Right column third line.")
    c.drawText(text_obj)

    c.save()
    return path


if __name__ == "__main__":
    paths = generate_all()
    for name, p in paths.items():
        print(f"  {name}: {p}")
