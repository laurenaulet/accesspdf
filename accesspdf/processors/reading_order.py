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
            y_pos, x_pos = self._get_position(kid, pdf)
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

    def _get_position(
        self, elem: pikepdf.Dictionary, pdf: pikepdf.Pdf
    ) -> tuple[float, float]:
        """Get approximate (y, x) position of a structure element's text.

        Scans the page content stream to find the text matrix (Tm) or
        text position (Td/TD) active when the element's MCID is rendered.
        Returns (y_position, x_position) in page coordinates.
        Falls back to MCID-based ordering if position can't be determined.
        """
        if "/K" not in elem or "/Pg" not in elem:
            return (0.0, 0.0)

        kids = elem["/K"]
        mcid: int | None = None
        if isinstance(kids, pikepdf.Array):
            for kid in kids:
                try:
                    mcid = int(kid)
                    break
                except (TypeError, ValueError):
                    pass
        else:
            try:
                mcid = int(kids)
            except (TypeError, ValueError):
                pass

        if mcid is None:
            return (0.0, 0.0)

        # Scan the page's content stream to find position at this MCID
        page_ref = elem["/Pg"]
        try:
            ops = pikepdf.parse_content_stream(page_ref)
        except Exception:
            return (float(-mcid), 0.0)  # fallback to MCID order

        # Track text position state
        tx, ty = 0.0, 0.0
        in_target_mcid = False

        for operands, operator in ops:
            op = str(operator)
            if op == "BDC" and len(operands) >= 2:
                props = operands[1]
                if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                    try:
                        if int(props["/MCID"]) == mcid:
                            in_target_mcid = True
                    except (TypeError, ValueError):
                        pass
            elif op == "EMC":
                if in_target_mcid:
                    break  # found our position
                in_target_mcid = False
            elif op == "Tm" and len(operands) >= 6:
                try:
                    tx = float(operands[4])
                    ty = float(operands[5])
                except (ValueError, TypeError):
                    pass
            elif op in ("Td", "TD") and len(operands) >= 2:
                try:
                    tx += float(operands[0])
                    ty += float(operands[1])
                except (ValueError, TypeError):
                    pass
            elif op == "BT":
                tx, ty = 0.0, 0.0

            if in_target_mcid and ty != 0.0:
                break  # got position inside our target MCID

        if ty == 0.0 and tx == 0.0:
            return (float(-mcid), 0.0)  # fallback to MCID order

        return (ty, tx)
