"""HeadingsProcessor — identifies and tags headings (H1-H6) based on font analysis."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import walk_struct_tree
from accesspdf.processors._text_extract import TextBlock, is_bold_font

logger = logging.getLogger(__name__)


@register_processor
class HeadingsProcessor:
    @property
    def name(self) -> str:
        return "Headings"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._process_headings(pdf)
        except Exception as exc:
            logger.error("HeadingsProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _process_headings(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        if "/StructTreeRoot" not in pdf.Root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Extract text blocks with font info from content streams
        blocks = self._extract_text_with_fonts(pdf)
        if not blocks:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Determine body font size (most common)
        body_size = self._get_body_font_size(blocks)
        if body_size is None:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Build heading level map
        heading_map = self._build_heading_map(blocks, body_size)
        if not heading_map:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Walk the structure tree and promote /P to /Hx
        struct_root = pdf.Root["/StructTreeRoot"]
        changes = self._promote_headings(struct_root, heading_map, pdf)

        warnings = self._check_nesting(struct_root)

        return ProcessorResult(
            processor_name=self.name,
            changes_made=changes,
            warnings=warnings,
        )

    def _extract_text_with_fonts(self, pdf: pikepdf.Pdf) -> list[dict]:
        """Extract text and font info directly from content streams."""
        blocks: list[dict] = []

        for page_idx, page in enumerate(pdf.pages):
            if "/Contents" not in page:
                continue
            try:
                ops = pikepdf.parse_content_stream(page)
                current_font = ""
                raw_font_size = 0.0
                tm_scale = 1.0  # vertical scale from text matrix (Tm)

                for operands, operator in ops:
                    # Track font changes: Tf operator sets font and raw size
                    if operator == pikepdf.Operator("Tf") and len(operands) >= 2:
                        current_font = str(operands[0])
                        try:
                            raw_font_size = float(operands[1])
                        except (ValueError, TypeError):
                            raw_font_size = 12.0

                    # Track text matrix: Tm sets [a b c d e f]
                    # Vertical scale factor is d (index 3)
                    elif operator == pikepdf.Operator("Tm") and len(operands) >= 6:
                        try:
                            tm_scale = abs(float(operands[3]))
                            if tm_scale == 0:
                                tm_scale = 1.0
                        except (ValueError, TypeError):
                            tm_scale = 1.0

                    # BT resets text matrix to identity
                    elif operator == pikepdf.Operator("BT"):
                        tm_scale = 1.0

                    # Text showing operators — effective size = raw * tm_scale
                    elif operator == pikepdf.Operator("Tj") and operands:
                        text = str(operands[0]).strip()
                        if text:
                            blocks.append({
                                "text": text,
                                "font": current_font,
                                "size": raw_font_size * tm_scale,
                                "bold": is_bold_font(current_font),
                                "page": page_idx,
                            })
                    elif operator == pikepdf.Operator("TJ") and operands:
                        parts = []
                        for item in operands[0]:
                            if isinstance(item, (pikepdf.String, str)):
                                parts.append(str(item))
                        text = "".join(parts).strip()
                        if text:
                            blocks.append({
                                "text": text,
                                "font": current_font,
                                "size": raw_font_size * tm_scale,
                                "bold": is_bold_font(current_font),
                                "page": page_idx,
                            })
            except Exception:
                logger.debug("Failed to parse content stream for page %d", page_idx)

        return blocks

    def _get_body_font_size(self, blocks: list[dict]) -> float | None:
        """Return the most common font size (the body text size)."""
        sizes = [b["size"] for b in blocks if b["size"] > 0]
        if not sizes:
            return None
        counter = Counter(sizes)
        return counter.most_common(1)[0][0]

    def _build_heading_map(
        self, blocks: list[dict], body_size: float
    ) -> dict[str, int]:
        """Map text content to heading levels based on font analysis.

        Returns {text: heading_level} for texts that should be headings.
        """
        heading_map: dict[str, int] = {}

        # Find font sizes larger than body text
        heading_sizes = sorted(
            {b["size"] for b in blocks if b["size"] > body_size * 1.15},
            reverse=True,
        )

        if not heading_sizes:
            # Check for bold text at body size
            for block in blocks:
                if block["bold"] and block["size"] >= body_size:
                    heading_map[block["text"]] = 2
            return heading_map

        # Map sizes to levels
        size_to_level: dict[float, int] = {}
        for i, size in enumerate(heading_sizes):
            size_to_level[size] = min(i + 1, 6)

        for block in blocks:
            if block["size"] in size_to_level:
                heading_map[block["text"]] = size_to_level[block["size"]]

        return heading_map

    def _promote_headings(
        self,
        struct_root: pikepdf.Dictionary,
        heading_map: dict[str, int],
        pdf: pikepdf.Pdf,
    ) -> int:
        """Walk the tag tree and change /P to /Hx for matching elements."""
        elements = walk_struct_tree(struct_root)
        changes = 0

        for elem in elements:
            if "/S" not in elem:
                continue
            tag = str(elem["/S"])
            if tag != "/P":
                continue

            # Try to match this element's text content with heading_map
            text = self._get_elem_text(elem, pdf)
            if not text:
                continue

            # Check each heading text for a match (normalized comparison)
            text_norm = " ".join(text.split()).lower()
            for heading_text, level in heading_map.items():
                heading_norm = " ".join(heading_text.split()).lower()
                if not text_norm or not heading_norm:
                    continue
                # Require exact match or that one starts with the other
                # (to handle minor extraction differences), but only if
                # the shorter string is at least 4 chars to avoid false matches
                if text_norm == heading_norm:
                    elem["/S"] = pikepdf.Name(f"/H{level}")
                    changes += 1
                    break
                shorter = min(len(text_norm), len(heading_norm))
                if shorter >= 4 and (
                    text_norm.startswith(heading_norm)
                    or heading_norm.startswith(text_norm)
                ):
                    elem["/S"] = pikepdf.Name(f"/H{level}")
                    changes += 1
                    break

        return changes

    def _get_elem_text(self, elem: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> str:
        """Try to extract text content associated with a structure element."""
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

        # Find the page and extract text from the MCID'd content
        page = elem["/Pg"]
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            return ""

        current_mcid: int | None = None
        text_parts: list[str] = []

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
                    text_parts.append(str(operands[0]))
                elif operator == pikepdf.Operator("TJ") and operands:
                    for item in operands[0]:
                        if isinstance(item, (pikepdf.String, str)):
                            text_parts.append(str(item))

        return "".join(text_parts).strip()

    def _check_nesting(self, struct_root: pikepdf.Dictionary) -> list[str]:
        """Check heading nesting and return warnings for violations."""
        warnings: list[str] = []
        elements = walk_struct_tree(struct_root)
        last_level = 0

        for elem in elements:
            if "/S" not in elem:
                continue
            tag = str(elem["/S"])
            if tag.startswith("/H") and len(tag) == 3 and tag[2:].isdigit():
                level = int(tag[2:])
                if last_level > 0 and level > last_level + 1:
                    warnings.append(
                        f"Heading nesting skip: H{last_level} -> H{level}"
                    )
                last_level = level

        return warnings
