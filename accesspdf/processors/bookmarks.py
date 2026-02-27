"""BookmarksProcessor — creates PDF outline (bookmarks) from heading hierarchy."""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import walk_struct_tree

logger = logging.getLogger(__name__)


@register_processor
class BookmarksProcessor:
    @property
    def name(self) -> str:
        return "Bookmarks"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._create_bookmarks(pdf)
        except Exception as exc:
            logger.error("BookmarksProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _create_bookmarks(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        if "/StructTreeRoot" not in pdf.Root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        struct_root = pdf.Root["/StructTreeRoot"]

        # Collect headings from the tag tree
        headings = self._collect_headings(struct_root, pdf)
        if not headings:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Build outline using pikepdf's outline API
        with pdf.open_outline() as outline:
            # Clear existing outline
            outline.root.clear()
            self._build_outline_tree(headings, outline.root, pdf)

        return ProcessorResult(
            processor_name=self.name,
            changes_made=len(headings),
        )

    def _collect_headings(
        self, struct_root: pikepdf.Dictionary, pdf: pikepdf.Pdf
    ) -> list[dict]:
        """Collect heading elements with their level, text, and page."""
        headings: list[dict] = []
        elements = walk_struct_tree(struct_root)

        for elem in elements:
            if "/S" not in elem:
                continue
            tag = str(elem["/S"])
            if not (tag.startswith("/H") and len(tag) == 3 and tag[2:].isdigit()):
                continue

            level = int(tag[2:])
            text = self._get_heading_text(elem, pdf)
            page_num = self._get_page_number(elem, pdf)

            if text:
                headings.append({
                    "level": level,
                    "text": text,
                    "page_num": page_num,
                })

        return headings

    def _get_heading_text(self, elem: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> str:
        """Extract text content from a heading structure element."""
        if "/K" not in elem or "/Pg" not in elem:
            return ""

        kids = elem["/K"]
        mcids: list[int] = []
        if isinstance(kids, pikepdf.Array):
            for kid in kids:
                if isinstance(kid, int):
                    mcids.append(int(kid))
        elif isinstance(kids, int):
            mcids.append(int(kids))

        if not mcids:
            return ""

        page = elem["/Pg"]
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            return ""

        current_mcid: int | None = None
        parts: list[str] = []

        for operands, operator in ops:
            if operator == pikepdf.Operator("BDC") and len(operands) >= 2:
                if isinstance(operands[1], pikepdf.Dictionary):
                    mid = operands[1].get("/MCID")
                    if mid is not None and int(mid) in mcids:
                        current_mcid = int(mid)
            elif operator == pikepdf.Operator("EMC"):
                current_mcid = None
            elif current_mcid is not None:
                if operator == pikepdf.Operator("Tj") and operands:
                    parts.append(str(operands[0]))
                elif operator == pikepdf.Operator("TJ") and operands:
                    for item in operands[0]:
                        if isinstance(item, (pikepdf.String, str)):
                            parts.append(str(item))

        return "".join(parts).strip()

    def _get_page_number(self, elem: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> int:
        """Get the 0-based page index for a structure element."""
        if "/Pg" not in elem:
            return 0
        page_ref = elem["/Pg"]
        for idx, page in enumerate(pdf.pages):
            if page.objgen == page_ref.objgen:
                return idx
        return 0

    def _build_outline_tree(
        self,
        headings: list[dict],
        root: list,
        pdf: pikepdf.Pdf,
    ) -> None:
        """Build a nested outline tree from a flat heading list."""
        # Stack of (level, outline_items_list)
        stack: list[tuple[int, list]] = [(0, root)]

        for heading in headings:
            level = heading["level"]
            page_num = heading["page_num"]

            item = pikepdf.OutlineItem(heading["text"], page_num)

            # Pop stack until we find the right parent level
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()

            # Add to current parent
            parent_list = stack[-1][1]
            parent_list.append(item)

            # Push this item's children list for potential nested headings
            stack.append((level, item.children))
