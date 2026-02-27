"""PDF accessibility analyzer.

Reads a PDF and produces an AnalysisResult describing its structure, images,
tags, metadata, and any accessibility issues found.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pikepdf
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTFigure, LTImage

from accesspdf.models import (
    AccessibilityIssue,
    AnalysisResult,
    ImageInfo,
    Severity,
    TagInfo,
)

logger = logging.getLogger(__name__)


class PDFAnalyzer:
    """Analyzes a PDF file for accessibility compliance.

    Usage::

        analyzer = PDFAnalyzer()
        result = analyzer.analyze(Path("thesis.pdf"))
    """

    def analyze(self, pdf_path: Path) -> AnalysisResult:
        """Run a full accessibility analysis on *pdf_path*."""
        result = AnalysisResult(source_path=pdf_path)

        with pikepdf.open(pdf_path) as pdf:
            result.page_count = len(pdf.pages)
            self._check_metadata(pdf, result)
            self._check_tags(pdf, result)

        self._extract_images(pdf_path, result)
        self._build_issues(result)

        return result

    def _check_metadata(self, pdf: pikepdf.Pdf, result: AnalysisResult) -> None:
        """Inspect document metadata for title and language."""
        # Check for document title
        if pdf.docinfo and "/Title" in pdf.docinfo:
            title = str(pdf.docinfo["/Title"])
            if title.strip():
                result.title = title.strip()

        # Check for language
        if pdf.Root and "/Lang" in pdf.Root:
            result.has_lang = True
            result.detected_lang = str(pdf.Root["/Lang"])

    def _check_tags(self, pdf: pikepdf.Pdf, result: AnalysisResult) -> None:
        """Check whether the PDF has a tag structure."""
        if "/MarkInfo" in pdf.Root:
            mark_info = pdf.Root["/MarkInfo"]
            if "/Marked" in mark_info and bool(mark_info["/Marked"]):
                result.is_tagged = True

        if "/StructTreeRoot" not in pdf.Root:
            return

        struct_root = pdf.Root["/StructTreeRoot"]
        self._walk_struct_tree(struct_root, result)

    def _walk_struct_tree(self, node: pikepdf.Object, result: AnalysisResult) -> None:
        """Recursively walk the structure tree and collect TagInfo."""
        try:
            if "/S" in node:
                tag_type = str(node["/S"])[1:]  # strip leading /
                tag = TagInfo(tag_type=tag_type)

                if "/Alt" in node:
                    tag.has_alt_text = True
                    tag.alt_text = str(node["/Alt"])

                result.tags.append(tag)

            if "/K" in node:
                kids = node["/K"]
                if isinstance(kids, pikepdf.Array):
                    for child in kids:
                        if isinstance(child, pikepdf.Dictionary):
                            self._walk_struct_tree(child, result)
                elif isinstance(kids, pikepdf.Dictionary):
                    self._walk_struct_tree(kids, result)
        except Exception:
            logger.debug("Error walking struct tree node", exc_info=True)

    def _extract_images(self, pdf_path: Path, result: AnalysisResult) -> None:
        """Extract image metadata using pdfminer for position data."""
        try:
            for page_num, page_layout in enumerate(extract_pages(pdf_path), start=1):
                self._scan_layout(page_layout, page_num, pdf_path, result)
        except Exception:
            logger.warning("Image extraction failed", exc_info=True)
            result.issues.append(
                AccessibilityIssue(
                    rule="image-extraction",
                    severity=Severity.WARNING,
                    message="Failed to extract images from PDF.",
                )
            )

    def _scan_layout(
        self, element: object, page: int, pdf_path: Path, result: AnalysisResult
    ) -> None:
        """Recursively scan pdfminer layout elements for images."""
        if isinstance(element, LTImage):
            image_info = self._image_info_from_lt(element, page, pdf_path)
            if image_info:
                result.images.append(image_info)

        if isinstance(element, LTFigure):
            for child in element:
                self._scan_layout(child, page, pdf_path, result)
        elif hasattr(element, "__iter__"):
            for child in element:  # type: ignore[union-attr]
                self._scan_layout(child, page, pdf_path, result)

    def _image_info_from_lt(
        self, lt_image: LTImage, page: int, pdf_path: Path
    ) -> ImageInfo | None:
        """Build an ImageInfo from a pdfminer LTImage, hashing via pikepdf."""
        try:
            with pikepdf.open(pdf_path) as pdf:
                for pg in pdf.pages:
                    if "/Resources" not in pg or "/XObject" not in pg["/Resources"]:
                        continue
                    for _name, xobj in pg["/Resources"]["/XObject"].items():
                        xobj = xobj.resolve() if hasattr(xobj, "resolve") else xobj
                        if not isinstance(xobj, pikepdf.Stream):
                            continue
                        raw = bytes(xobj.read_raw_bytes())
                        img_hash = hashlib.md5(raw).hexdigest()
                        w = int(xobj.get("/Width", 0))
                        h = int(xobj.get("/Height", 0))
                        cs = str(xobj.get("/ColorSpace", ""))
                        return ImageInfo(
                            image_hash=img_hash,
                            page=page,
                            width=w,
                            height=h,
                            color_space=cs,
                            bbox=(lt_image.x0, lt_image.y0, lt_image.x1, lt_image.y1),
                        )
        except Exception:
            logger.debug("Could not hash image on page %d", page, exc_info=True)
        return None

    def _build_issues(self, result: AnalysisResult) -> None:
        """Generate accessibility issues from the analysis result."""
        if not result.is_tagged:
            result.issues.append(
                AccessibilityIssue(
                    rule="tagged-pdf",
                    severity=Severity.ERROR,
                    message="PDF is not tagged. Screen readers cannot interpret the document structure.",
                )
            )

        if not result.has_lang:
            result.issues.append(
                AccessibilityIssue(
                    rule="document-lang",
                    severity=Severity.ERROR,
                    message="Document language is not set.",
                )
            )

        if not result.title:
            result.issues.append(
                AccessibilityIssue(
                    rule="document-title",
                    severity=Severity.WARNING,
                    message="Document title is not set in metadata.",
                )
            )

        # Check for images without alt text
        figure_tags = [t for t in result.tags if t.tag_type == "Figure"]
        images_without_alt = [t for t in figure_tags if not t.has_alt_text]
        if images_without_alt:
            result.issues.append(
                AccessibilityIssue(
                    rule="image-alt-text",
                    severity=Severity.ERROR,
                    message=f"{len(images_without_alt)} image(s) missing alt text.",
                )
            )
