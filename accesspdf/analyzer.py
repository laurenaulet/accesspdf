"""PDF accessibility analyzer.

Reads a PDF and produces an AnalysisResult describing its structure, images,
tags, metadata, and any accessibility issues found.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import pikepdf

from accesspdf.models import (
    AccessibilityIssue,
    AnalysisResult,
    ImageInfo,
    Severity,
    TagInfo,
)
from accesspdf.utils.contrast import contrast_ratio, parse_pdf_color

logger = logging.getLogger(__name__)

WHITE = (255, 255, 255)

_AMBIGUOUS_LINK_TEXTS = frozenset({
    "click here",
    "here",
    "read more",
    "learn more",
    "link",
    "more",
    "more info",
    "more information",
    "details",
    "go",
    "see more",
})

_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)


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
            self._check_scanned(pdf, result)
            self._check_contrast(pdf, result)

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

    # ------------------------------------------------------------------
    # Scanned PDF detection
    # ------------------------------------------------------------------

    _TEXT_OPERATORS = frozenset({"Tj", "TJ", "'", '"'})

    def _check_scanned(self, pdf: pikepdf.Pdf, result: AnalysisResult) -> None:
        """Detect scanned (image-only) PDFs that lack a text layer."""
        if result.page_count == 0:
            return

        image_only_pages = 0

        for page in pdf.pages:
            try:
                has_image = self._page_has_image(page)
                has_text = self._page_has_text(page)
                if has_image and not has_text:
                    image_only_pages += 1
            except Exception:
                logger.debug("Could not check page for scanned content", exc_info=True)

        ratio = image_only_pages / result.page_count
        if ratio >= 0.9 and image_only_pages >= 1:
            result.is_scanned = True
            result.issues.append(
                AccessibilityIssue(
                    rule="scanned-pdf",
                    severity=Severity.WARNING,
                    message=(
                        "This PDF appears to be scanned (image-only pages with no "
                        "text layer). Accessibility fixes cannot add meaningful "
                        "structure. Run OCR software first to add a text layer."
                    ),
                )
            )

    def _page_has_image(self, page: pikepdf.Page) -> bool:
        """Return True if the page has at least one Image XObject."""
        if "/Resources" not in page or "/XObject" not in page["/Resources"]:
            return False
        for _name, xobj_ref in page["/Resources"]["/XObject"].items():
            try:
                xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
                if isinstance(xobj, pikepdf.Stream):
                    subtype = str(xobj.get("/Subtype", ""))
                    if subtype == "/Image":
                        return True
            except Exception:
                pass
        return False

    def _page_has_text(self, page: pikepdf.Page) -> bool:
        """Return True if the page's content stream has text-rendering operators."""
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            return False
        for _operands, operator in ops:
            if str(operator) in self._TEXT_OPERATORS:
                return True
        return False

    # ------------------------------------------------------------------
    # Contrast checking (WCAG 1.4.3)
    # ------------------------------------------------------------------

    def _check_contrast(self, pdf: pikepdf.Pdf, result: AnalysisResult) -> None:
        """Extract text colors from content streams and flag low contrast."""
        low_contrast_pages: list[int] = []
        very_low_contrast_pages: list[int] = []

        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                colors = self._extract_text_colors(page)
                for color in colors:
                    ratio = contrast_ratio(color, WHITE)
                    if ratio < 3.0:
                        very_low_contrast_pages.append(page_num)
                        break
                    elif ratio < 4.5:
                        low_contrast_pages.append(page_num)
                        break
            except Exception:
                logger.debug(
                    "Could not check contrast on page %d", page_num, exc_info=True
                )

        if very_low_contrast_pages:
            pages_str = ", ".join(str(p) for p in very_low_contrast_pages[:5])
            suffix = (
                f" and {len(very_low_contrast_pages) - 5} more"
                if len(very_low_contrast_pages) > 5
                else ""
            )
            result.issues.append(
                AccessibilityIssue(
                    rule="contrast-very-low",
                    severity=Severity.ERROR,
                    message=(
                        f"Very low text contrast (ratio < 3:1) on page(s) "
                        f"{pages_str}{suffix}."
                    ),
                )
            )

        if low_contrast_pages:
            pages_str = ", ".join(str(p) for p in low_contrast_pages[:5])
            suffix = (
                f" and {len(low_contrast_pages) - 5} more"
                if len(low_contrast_pages) > 5
                else ""
            )
            result.issues.append(
                AccessibilityIssue(
                    rule="contrast-low",
                    severity=Severity.WARNING,
                    message=(
                        f"Low text contrast (ratio < 4.5:1) on page(s) "
                        f"{pages_str}{suffix}."
                    ),
                )
            )

    def _extract_text_colors(self, page: pikepdf.Page) -> list[tuple[int, int, int]]:
        """Parse content stream operators to find text fill colors."""
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            return []

        colors: list[tuple[int, int, int]] = []
        current_fill: tuple[int, int, int] = (0, 0, 0)  # default: black
        seen: set[tuple[int, int, int]] = set()
        in_text = False

        for operands, operator in ops:
            op = str(operator)

            # Track text blocks
            if op == "BT":
                in_text = True
            elif op == "ET":
                in_text = False

            # Non-stroking (fill) color operators
            elif op == "rg" and len(operands) >= 3:
                current_fill = parse_pdf_color(
                    [float(o) for o in operands[:3]], "rgb"
                )
            elif op == "g" and len(operands) >= 1:
                current_fill = parse_pdf_color(
                    [float(operands[0])], "gray"
                )
            elif op == "k" and len(operands) >= 4:
                current_fill = parse_pdf_color(
                    [float(o) for o in operands[:4]], "cmyk"
                )

            # Text-showing operators: Tj, TJ, ', "
            elif op in ("Tj", "TJ", "'", '"') and in_text:
                if current_fill not in seen:
                    seen.add(current_fill)
                    colors.append(current_fill)

        return colors

    # ------------------------------------------------------------------
    # Issue building
    # ------------------------------------------------------------------

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

        self._check_links(result)
        self._check_tables(result)

    # ------------------------------------------------------------------
    # Link validation (WCAG 2.4.4)
    # ------------------------------------------------------------------

    def _check_links(self, result: AnalysisResult) -> None:
        """Check link tags for ambiguous, bare-URL, or empty link text."""
        link_tags = [t for t in result.tags if t.tag_type == "Link"]
        if not link_tags:
            return

        ambiguous_count = 0
        bare_url_count = 0
        empty_count = 0

        for tag in link_tags:
            text = tag.alt_text.strip()
            if not text or text == "Link":
                empty_count += 1
            elif text.lower() in _AMBIGUOUS_LINK_TEXTS:
                ambiguous_count += 1
            elif _URL_PATTERN.match(text):
                bare_url_count += 1

        if empty_count:
            result.issues.append(
                AccessibilityIssue(
                    rule="link-empty-text",
                    severity=Severity.ERROR,
                    message=f"{empty_count} link(s) have no descriptive text.",
                )
            )

        if ambiguous_count:
            result.issues.append(
                AccessibilityIssue(
                    rule="link-ambiguous-text",
                    severity=Severity.WARNING,
                    message=(
                        f"{ambiguous_count} link(s) use ambiguous text "
                        f'(e.g. "click here", "read more").'
                    ),
                )
            )

        if bare_url_count:
            result.issues.append(
                AccessibilityIssue(
                    rule="link-bare-url",
                    severity=Severity.INFO,
                    message=f"{bare_url_count} link(s) use a bare URL as link text.",
                )
            )

    # ------------------------------------------------------------------
    # Table validation
    # ------------------------------------------------------------------

    def _check_tables(self, result: AnalysisResult) -> None:
        """Check table structure for headers and scope attributes."""
        table_tags = [t for t in result.tags if t.tag_type == "Table"]
        th_tags = [t for t in result.tags if t.tag_type == "TH"]

        if table_tags and not th_tags:
            result.issues.append(
                AccessibilityIssue(
                    rule="table-no-headers",
                    severity=Severity.WARNING,
                    message=f"{len(table_tags)} table(s) have no header cells (TH).",
                )
            )
