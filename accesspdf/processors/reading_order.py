"""ReadingOrderProcessor — reorders tag tree by geometric reading position."""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import parse_content_stream_safe

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

        # Pre-parse content streams once per page and build MCID position maps
        mcid_positions = self._build_mcid_position_map(pdf)

        # Sort structure elements by page, then by position (top-to-bottom)
        sortable: list[tuple[int, float, float, int, pikepdf.Object]] = []

        for idx, kid in enumerate(kids):
            if not isinstance(kid, pikepdf.Dictionary):
                sortable.append((0, 0.0, 0.0, idx, kid))
                continue

            page_idx = self._get_page_index(kid, pdf)
            y_pos, x_pos = self._get_position(kid, page_idx, mcid_positions)
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

    def _build_mcid_position_map(
        self, pdf: pikepdf.Pdf
    ) -> dict[int, dict[int, tuple[float, float]]]:
        """Parse each page's content stream once and map MCID -> (y, x) position.

        Returns {page_index: {mcid: (ty, tx), ...}, ...}
        """
        result: dict[int, dict[int, tuple[float, float]]] = {}

        for page_idx, page in enumerate(pdf.pages):
            if "/Contents" not in page:
                continue

            ops = parse_content_stream_safe(page, page_idx)
            if ops is None:
                continue

            mcid_map: dict[int, tuple[float, float]] = {}
            tx, ty = 0.0, 0.0
            current_mcid: int | None = None

            for operands, operator in ops:
                op = str(operator)

                if op == "BT":
                    tx, ty = 0.0, 0.0
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
                elif op == "BDC" and len(operands) >= 2:
                    props = operands[1]
                    if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                        try:
                            current_mcid = int(props["/MCID"])
                        except (TypeError, ValueError):
                            current_mcid = None
                elif op == "EMC":
                    current_mcid = None

                # Record the first non-zero position we see inside each MCID
                if current_mcid is not None and current_mcid not in mcid_map:
                    if ty != 0.0 or tx != 0.0:
                        mcid_map[current_mcid] = (ty, tx)

            if mcid_map:
                result[page_idx] = mcid_map

        return result

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
        self,
        elem: pikepdf.Dictionary,
        page_idx: int,
        mcid_positions: dict[int, dict[int, tuple[float, float]]],
    ) -> tuple[float, float]:
        """Look up (y, x) position from the pre-built MCID position map."""
        if "/K" not in elem:
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

        page_map = mcid_positions.get(page_idx, {})
        pos = page_map.get(mcid)
        if pos is not None:
            return pos

        # Fallback to MCID order
        return (float(-mcid), 0.0)
