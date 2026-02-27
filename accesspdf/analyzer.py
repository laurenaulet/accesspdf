"""PDF accessibility analyzer.

Reads a PDF and produces an AnalysisResult describing its structure, images,
tags, metadata, and any accessibility issues found.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pikepdf

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
            self._extract_images_from_xobjects(pdf, result)

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

    def _extract_images_from_xobjects(
        self, pdf: pikepdf.Pdf, result: AnalysisResult
    ) -> None:
        """Extract all image XObjects from the PDF, deduplicating by hash."""
        seen_hashes: set[str] = set()
        try:
            for page_idx, page in enumerate(pdf.pages, start=1):
                self._scan_page_xobjects(page, page_idx, seen_hashes, result)
        except Exception:
            logger.warning("Image extraction failed", exc_info=True)
            result.issues.append(
                AccessibilityIssue(
                    rule="image-extraction",
                    severity=Severity.WARNING,
                    message="Failed to extract images from PDF.",
                )
            )

    def _scan_page_xobjects(
        self,
        page: pikepdf.Page,
        page_num: int,
        seen_hashes: set[str],
        result: AnalysisResult,
    ) -> None:
        """Scan a single page for image XObjects."""
        if "/Resources" not in page or "/XObject" not in page["/Resources"]:
            return

        for _name, xobj_ref in page["/Resources"]["/XObject"].items():
            try:
                xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
                if not isinstance(xobj, pikepdf.Stream):
                    continue

                # Skip form XObjects that aren't images — check /Subtype
                subtype = str(xobj.get("/Subtype", ""))
                if subtype == "/Form":
                    # Form XObjects can contain images; recurse into them
                    self._scan_form_xobject(xobj, page_num, seen_hashes, result)
                    continue
                if subtype != "/Image":
                    continue

                raw = bytes(xobj.read_raw_bytes())
                img_hash = hashlib.md5(raw).hexdigest()

                if img_hash in seen_hashes:
                    continue
                seen_hashes.add(img_hash)

                w = int(xobj.get("/Width", 0))
                h = int(xobj.get("/Height", 0))
                cs = str(xobj.get("/ColorSpace", ""))

                result.images.append(
                    ImageInfo(
                        image_hash=img_hash,
                        page=page_num,
                        width=w,
                        height=h,
                        color_space=cs,
                    )
                )
            except Exception:
                logger.debug("Could not process XObject on page %d", page_num, exc_info=True)

    def _scan_form_xobject(
        self,
        form_xobj: pikepdf.Stream,
        page_num: int,
        seen_hashes: set[str],
        result: AnalysisResult,
    ) -> None:
        """Recurse into a Form XObject to find embedded images."""
        try:
            resources = form_xobj.get("/Resources")
            if resources is None or "/XObject" not in resources:
                return
            for _name, inner_ref in resources["/XObject"].items():
                inner = inner_ref.resolve() if hasattr(inner_ref, "resolve") else inner_ref
                if not isinstance(inner, pikepdf.Stream):
                    continue
                subtype = str(inner.get("/Subtype", ""))
                if subtype != "/Image":
                    continue

                raw = bytes(inner.read_raw_bytes())
                img_hash = hashlib.md5(raw).hexdigest()
                if img_hash in seen_hashes:
                    continue
                seen_hashes.add(img_hash)

                w = int(inner.get("/Width", 0))
                h = int(inner.get("/Height", 0))
                cs = str(inner.get("/ColorSpace", ""))

                result.images.append(
                    ImageInfo(
                        image_hash=img_hash,
                        page=page_num,
                        width=w,
                        height=h,
                        color_space=cs,
                    )
                )
        except Exception:
            logger.debug("Could not scan form XObject on page %d", page_num, exc_info=True)

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
