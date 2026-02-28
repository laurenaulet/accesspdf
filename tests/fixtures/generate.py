"""Generate synthetic test PDFs for processor testing using reportlab."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
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
        "images": generate_images_pdf(CORPUS_DIR),
        "low_contrast": generate_low_contrast_pdf(CORPUS_DIR),
        "ambiguous_links": generate_ambiguous_links_pdf(CORPUS_DIR),
        "scanned": generate_scanned_pdf(CORPUS_DIR),
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


def generate_images_pdf(output_dir: Path) -> Path:
    """PDF with embedded images for alt text testing."""
    import io
    import tempfile

    from PIL import Image as PILImage, ImageDraw

    path = output_dir / "images.pdf"

    # Create synthetic images as temporary files (reportlab needs file paths)
    img_files: list[str] = []
    temp_dir = Path(tempfile.mkdtemp())

    # Image 1: blue rectangle with a circle (simulating a chart)
    img1 = PILImage.new("RGB", (200, 150), color=(240, 240, 255))
    draw1 = ImageDraw.Draw(img1)
    draw1.rectangle([20, 20, 180, 130], outline=(0, 0, 180), width=2)
    draw1.ellipse([60, 40, 140, 110], fill=(0, 100, 200))
    img1_path = temp_dir / "chart.png"
    img1.save(str(img1_path))
    img_files.append(str(img1_path))

    # Image 2: red/green gradient (simulating a photo)
    img2 = PILImage.new("RGB", (160, 120), color=(200, 255, 200))
    draw2 = ImageDraw.Draw(img2)
    draw2.polygon([(80, 10), (150, 110), (10, 110)], fill=(200, 50, 50))
    img2_path = temp_dir / "photo.png"
    img2.save(str(img2_path))
    img_files.append(str(img2_path))

    # Image 3: small icon (simulating a decorative element)
    img3 = PILImage.new("RGB", (40, 40), color=(255, 255, 255))
    draw3 = ImageDraw.Draw(img3)
    draw3.ellipse([5, 5, 35, 35], fill=(255, 200, 0))
    img3_path = temp_dir / "icon.png"
    img3.save(str(img3_path))
    img_files.append(str(img3_path))

    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()

    story = [
        Paragraph("Images Test Document", styles["Title"]),
        Spacer(1, 12),
        Paragraph("Below is a chart showing sample data:", styles["Normal"]),
        Spacer(1, 6),
        Image(img_files[0], width=200, height=150),
        Spacer(1, 12),
        Paragraph("Here is a photograph from the field study:", styles["Normal"]),
        Spacer(1, 6),
        Image(img_files[1], width=160, height=120),
        Spacer(1, 12),
        Paragraph("Decorative separator:", styles["Normal"]),
        Image(img_files[2], width=40, height=40),
        Spacer(1, 12),
        Paragraph("This text follows the images.", styles["Normal"]),
    ]
    doc.build(story)

    # Clean up temp files
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

    return path


def generate_low_contrast_pdf(output_dir: Path) -> Path:
    """PDF with light gray text on white background — fails WCAG AA contrast."""
    path = output_dir / "low_contrast.pdf"

    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    # Light gray text (RGB ~0.85) on white: contrast ratio ~1.9:1, well below 4.5:1
    c.setFillColorRGB(0.85, 0.85, 0.85)
    text_obj = c.beginText(72, height - 72)
    text_obj.setFont("Helvetica", 12)
    text_obj.textLine("This text is very light gray and hard to read.")
    text_obj.textLine("It should fail WCAG AA contrast requirements.")
    c.drawText(text_obj)

    # Also add some readable black text for comparison
    c.setFillColorRGB(0, 0, 0)
    text_obj2 = c.beginText(72, height - 150)
    text_obj2.setFont("Helvetica", 12)
    text_obj2.textLine("This text is black and fully readable.")
    c.drawText(text_obj2)

    c.save()
    return path


def generate_ambiguous_links_pdf(output_dir: Path) -> Path:
    """PDF with ambiguous link text like 'click here' and bare URLs."""
    path = output_dir / "ambiguous_links.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()

    story = [
        Paragraph("Ambiguous Links Test", styles["Title"]),
        Spacer(1, 12),
        Paragraph(
            'For more information, <a href="https://example.com">click here</a>.',
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            'Visit <a href="https://example.org">https://example.org</a> for details.',
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            '<a href="https://good.example.com">AccessPDF Documentation</a> is also available.',
            styles["Normal"],
        ),
    ]
    doc.build(story)
    return path


def generate_scanned_pdf(output_dir: Path) -> Path:
    """PDF that simulates a scanned document -- pages are just full-page images with no text."""
    from PIL import Image as PILImage, ImageDraw

    path = output_dir / "scanned.pdf"

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    # Create a couple of synthetic "scan" images (like photographed pages)
    import tempfile

    temp_dir = Path(tempfile.mkdtemp())
    img_paths = []
    for i in range(3):
        img = PILImage.new("RGB", (612, 792), color=(250, 248, 245))
        draw = ImageDraw.Draw(img)
        # Draw some "text-like" lines to mimic a scanned page
        y = 72
        for _ in range(20):
            draw.rectangle([72, y, 540, y + 8], fill=(40, 40, 40))
            y += 24
        img_path = temp_dir / f"page_{i}.png"
        img.save(str(img_path))
        img_paths.append(str(img_path))

    c = canvas.Canvas(str(path), pagesize=letter)
    w, h = letter
    for img_file in img_paths:
        c.drawImage(img_file, 0, 0, width=w, height=h)
        c.showPage()
    c.save()

    # Clean up temp images
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

    return path


if __name__ == "__main__":
    paths = generate_all()
    for name, p in paths.items():
        print(f"  {name}: {p}")
