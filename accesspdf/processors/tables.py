"""TablesProcessor — detects simple ruled tables and creates table structure tags.

Handles tables with visible ruling lines forming a regular grid.  Header cells
(TH) get unique /ID attributes and /Scope, and data cells (TD) get /Headers
references so screen readers can associate cells with their headers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import add_kid, make_struct_elem, walk_struct_tree

logger = logging.getLogger(__name__)


@dataclass
class TableGrid:
    """A detected table grid on a page."""

    page_idx: int
    row_positions: list[float]  # y-coordinates of horizontal separators
    col_positions: list[float]  # x-coordinates of vertical separators

    @property
    def num_rows(self) -> int:
        return max(0, len(self.row_positions) - 1)

    @property
    def num_cols(self) -> int:
        return max(0, len(self.col_positions) - 1)


@register_processor
class TablesProcessor:
    @property
    def name(self) -> str:
        return "Tables"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._process_tables(pdf)
        except Exception as exc:
            logger.error("TablesProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _process_tables(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        if "/StructTreeRoot" not in pdf.Root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        struct_root = pdf.Root["/StructTreeRoot"]

        # Check if table tags already exist
        existing = walk_struct_tree(struct_root)
        has_tables = any(
            str(e.get("/S", "")) == "/Table" for e in existing
        )
        if has_tables:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Detect tables from content stream line drawing operations
        grids = self._detect_tables_from_streams(pdf)
        if not grids:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        changes = 0
        # Get the document element
        root_kids = struct_root["/K"]
        if isinstance(root_kids, pikepdf.Array) and len(root_kids) > 0:
            doc_elem = root_kids[0]
        elif isinstance(root_kids, pikepdf.Dictionary):
            doc_elem = root_kids
        else:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        table_counter = 0
        for grid in grids:
            table_counter += 1
            page = pdf.pages[grid.page_idx]
            table_elem = make_struct_elem(pdf, "Table", doc_elem, page=page)

            # Build header IDs so data cells can reference them
            header_ids: list[str] = []
            for col_idx in range(grid.num_cols):
                header_ids.append(f"t{table_counter}_c{col_idx + 1}")

            for row_idx in range(grid.num_rows):
                tr_elem = make_struct_elem(pdf, "TR", table_elem, page=page)
                add_kid(table_elem, tr_elem)

                for col_idx in range(grid.num_cols):
                    cell_tag = "TH" if row_idx == 0 else "TD"
                    cell_elem = make_struct_elem(pdf, cell_tag, tr_elem, page=page)
                    if row_idx == 0:
                        cell_elem["/ID"] = pikepdf.String(header_ids[col_idx])
                        cell_elem["/A"] = pikepdf.Dictionary({
                            "/O": pikepdf.Name("/Table"),
                            "/Scope": pikepdf.Name("/Column"),
                        })
                    else:
                        # Data cells reference their column header
                        cell_elem["/Headers"] = pikepdf.Array([
                            pikepdf.String(header_ids[col_idx])
                        ])
                    add_kid(tr_elem, cell_elem)

            add_kid(doc_elem, table_elem)
            changes += 1

        warnings = []
        if changes > 0:
            warnings.append(
                f"Detected {changes} table(s) with structural tags only. "
                "Cell content is not linked -- manual review recommended."
            )
        return ProcessorResult(
            processor_name=self.name, changes_made=changes, warnings=warnings
        )

    def _detect_tables_from_streams(self, pdf: pikepdf.Pdf) -> list[TableGrid]:
        """Detect table grids from line-drawing operators in content streams."""
        grids: list[TableGrid] = []

        for page_idx, page in enumerate(pdf.pages):
            if "/Contents" not in page:
                continue

            try:
                ops = pikepdf.parse_content_stream(page)
            except Exception:
                continue

            h_lines: list[tuple[float, float, float, float]] = []
            v_lines: list[tuple[float, float, float, float]] = []
            current_x = 0.0
            current_y = 0.0

            for operands, operator in ops:
                op = str(operator)
                if op == "m" and len(operands) >= 2:
                    current_x = float(operands[0])
                    current_y = float(operands[1])
                elif op == "l" and len(operands) >= 2:
                    x1 = float(operands[0])
                    y1 = float(operands[1])
                    dx = abs(x1 - current_x)
                    dy = abs(y1 - current_y)
                    min_length = 20.0

                    if dy < 2.0 and dx > min_length:
                        h_lines.append((
                            min(current_x, x1), current_y,
                            max(current_x, x1), y1,
                        ))
                    elif dx < 2.0 and dy > min_length:
                        v_lines.append((
                            current_x, min(current_y, y1),
                            x1, max(current_y, y1),
                        ))
                    current_x = x1
                    current_y = y1
                elif op == "re" and len(operands) >= 4:
                    # Rectangle: x y w h
                    rx = float(operands[0])
                    ry = float(operands[1])
                    rw = float(operands[2])
                    rh = float(operands[3])
                    if rw > 20 and rh > 5:
                        h_lines.append((rx, ry, rx + rw, ry))
                        h_lines.append((rx, ry + rh, rx + rw, ry + rh))
                        v_lines.append((rx, ry, rx, ry + rh))
                        v_lines.append((rx + rw, ry, rx + rw, ry + rh))

            grid = self._find_grid(h_lines, v_lines, page_idx)
            if grid:
                grids.append(grid)

        return grids

    def _find_grid(
        self,
        h_lines: list[tuple[float, float, float, float]],
        v_lines: list[tuple[float, float, float, float]],
        page_idx: int,
        tolerance: float = 3.0,
    ) -> TableGrid | None:
        """Find a regular grid pattern from lines."""
        if len(h_lines) < 2 or len(v_lines) < 2:
            return None

        # Cluster horizontal lines by y-position
        h_y_positions = sorted({round(l[1] / tolerance) * tolerance for l in h_lines})
        v_x_positions = sorted({round(l[0] / tolerance) * tolerance for l in v_lines})

        # Need at least 3 horizontal (2 rows) and 3 vertical (2 cols) lines
        if len(h_y_positions) < 3 or len(v_x_positions) < 3:
            return None

        return TableGrid(
            page_idx=page_idx,
            row_positions=h_y_positions,
            col_positions=v_x_positions,
        )
