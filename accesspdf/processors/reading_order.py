"""ReadingOrderProcessor — reorders tag tree by geometric reading position."""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor

logger = logging.getLogger(__name__)


@register_processor
class ReadingOrderProcessor:
    @property
    def name(self) -> str:
        return "ReadingOrder"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._reorder(pdf)
        except Exception as exc:
            logger.error("ReadingOrderProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _reorder(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        if "/StructTreeRoot" not in pdf.Root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        struct_root = pdf.Root["/StructTreeRoot"]
        if "/K" not in struct_root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Get the document element (first child of root)
        root_kids = struct_root["/K"]
        if isinstance(root_kids, pikepdf.Array) and len(root_kids) > 0:
            doc_elem = root_kids[0]
        elif isinstance(root_kids, pikepdf.Dictionary):
            doc_elem = root_kids
        else:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        if "/K" not in doc_elem:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        kids = doc_elem["/K"]
        if not isinstance(kids, pikepdf.Array) or len(kids) < 2:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Sort structure elements by page, then by position (top-to-bottom)
        sortable: list[tuple[int, float, float, int, pikepdf.Object]] = []

        for idx, kid in enumerate(kids):
            if not isinstance(kid, pikepdf.Dictionary):
                sortable.append((0, 0.0, 0.0, idx, kid))
                continue

            page_idx = self._get_page_index(kid, pdf)
            y_pos, x_pos = self._get_position(kid)
            sortable.append((page_idx, -y_pos, x_pos, idx, kid))

        # Sort by page, then top-to-bottom (negate y for descending), then left-to-right
        sortable.sort(key=lambda t: (t[0], t[1], t[2]))

        # Check if order actually changed
        new_order = [item[4] for item in sortable]
        original_order = list(kids)

        changed = False
        for i, (new, orig) in enumerate(zip(new_order, original_order)):
            if not isinstance(new, type(orig)):
                changed = True
                break
            if isinstance(new, pikepdf.Dictionary) and isinstance(orig, pikepdf.Dictionary):
                if new.objgen != orig.objgen:
                    changed = True
                    break

        if not changed:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        doc_elem["/K"] = pikepdf.Array(new_order)
        return ProcessorResult(processor_name=self.name, changes_made=1)

    def _get_page_index(self, elem: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> int:
        """Get the page index for a structure element."""
        if "/Pg" not in elem:
            return 0
        page_ref = elem["/Pg"]
        for idx, page in enumerate(pdf.pages):
            if page.objgen == page_ref.objgen:
                return idx
        return 0

    def _get_position(self, elem: pikepdf.Dictionary) -> tuple[float, float]:
        """Get approximate (y, x) position from a structure element's MCID.

        Returns (y_position, x_position) in page coordinates.
        For now, uses the MCID as a proxy for order (lower MCID = earlier in stream).
        """
        if "/K" not in elem:
            return (0.0, 0.0)

        kids = elem["/K"]
        if isinstance(kids, pikepdf.Array):
            for kid in kids:
                if isinstance(kid, int):
                    # MCID — use as order proxy (content stream order)
                    return (float(-kid), 0.0)
        elif isinstance(kids, int):
            return (float(-int(kids)), 0.0)

        return (0.0, 0.0)
