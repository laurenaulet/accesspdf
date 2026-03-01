"""BookmarksProcessor — creates PDF outline (bookmarks) from heading hierarchy."""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import parse_content_stream_safe, walk_struct_tree

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

        # Pre-build MCID text cache (parse each page once)
        mcid_text_cache = self._build_mcid_text_cache(pdf)

        # Collect headings from the tag tree
        headings = self._collect_headings(struct_root, pdf, mcid_text_cache)
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

    def _build_mcid_text_cache(
        self, pdf: pikepdf.Pdf
    ) -> dict[int, dict[int, str]]:
        """Parse each page once and build {page_objgen_hash: {mcid: text}}."""
        cache: dict[int, dict[int, str]] = {}

        for page_idx, page in enumerate(pdf.pages):
            if "/Contents" not in page:
                continue

            ops = parse_content_stream_safe(page, page_idx)
            if ops is None:
                continue

            mcid_texts: dict[int, list[str]] = {}
            current_mcid: int | None = None

            for operands, operator in ops:
                if operator == pikepdf.Operator("BDC") and len(operands) >= 2:
                    if isinstance(operands[1], pikepdf.Dictionary):
                        mid = operands[1].get("/MCID")
                        if mid is not None:
                            try:
                                current_mcid = int(mid)
                            except (TypeError, ValueError):
                                current_mcid = None
                elif operator == pikepdf.Operator("EMC"):
                    current_mcid = None
                elif current_mcid is not None:
                    if operator == pikepdf.Operator("Tj") and operands:
                        mcid_texts.setdefault(current_mcid, []).append(
                            str(operands[0])
                        )
                    elif operator == pikepdf.Operator("TJ") and operands:
                        for item in operands[0]:
                            if isinstance(item, (pikepdf.String, str)):
                                mcid_texts.setdefault(current_mcid, []).append(
                                    str(item)
                                )

            page_obj = page.obj if hasattr(page, "obj") else page
            key = hash(page_obj.objgen)
            cache[key] = {
                mcid: "".join(parts).strip()
                for mcid, parts in mcid_texts.items()
            }

        return cache

    def _collect_headings(
        self,
        struct_root: pikepdf.Dictionary,
        pdf: pikepdf.Pdf,
        mcid_text_cache: dict[int, dict[int, str]],
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
            text = self._get_heading_text_cached(elem, mcid_text_cache)
            page_num = self._get_page_number(elem, pdf)

            if text:
                headings.append({
                    "level": level,
                    "text": text,
                    "page_num": page_num,
                })

        return headings

    def _get_heading_text_cached(
        self,
        elem: pikepdf.Dictionary,
        mcid_text_cache: dict[int, dict[int, str]],
    ) -> str:
        """Look up text for a heading element from the pre-built cache."""
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

        page_ref = elem["/Pg"]
        page_obj = page_ref.obj if hasattr(page_ref, "obj") else page_ref
        key = hash(page_obj.objgen)
        page_cache = mcid_text_cache.get(key, {})

        parts = []
        for mcid in mcids:
            text = page_cache.get(mcid, "")
            if text:
                parts.append(text)

        return " ".join(parts).strip()

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
