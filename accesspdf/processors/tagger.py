"""TaggerProcessor — creates tag structure for untagged PDFs.

This is the foundational processor.  It creates a StructTreeRoot, MarkInfo,
and ParentTree if they don't exist, then wraps page content in marked content
sequences with /P structure elements.  All other processors depend on this
having run first.
"""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import (
    add_kid,
    ensure_mark_info,
    ensure_parent_tree,
    ensure_struct_tree_root,
    make_struct_elem,
)

logger = logging.getLogger(__name__)


@register_processor
class TaggerProcessor:
    @property
    def name(self) -> str:
        return "TagStructure"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._tag(pdf)
        except Exception as exc:
            logger.error("TaggerProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _tag(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        # Check if already properly tagged
        if self._is_already_tagged(pdf):
            # Even if already tagged, ensure every page has /Tabs /S
            tabs_added = self._ensure_tabs(pdf)
            return ProcessorResult(processor_name=self.name, changes_made=tabs_added)

        struct_root = ensure_struct_tree_root(pdf)
        ensure_mark_info(pdf)
        parent_tree = ensure_parent_tree(struct_root, pdf)

        # Create root /Document element
        doc_elem = make_struct_elem(pdf, "Document", struct_root)
        struct_root["/K"] = pikepdf.Array([doc_elem])

        total_mcids = 0
        parent_tree_nums = pikepdf.Array()

        for page_idx, page in enumerate(pdf.pages):
            mcids_on_page = self._tag_page(pdf, page, doc_elem, page_idx)
            total_mcids += mcids_on_page

            # Build parent tree entry for this page: page_idx -> array of struct elems
            page["/StructParents"] = page_idx
            # /Tabs /S tells readers to use structure order for tab/reading order
            page["/Tabs"] = pikepdf.Name("/S")

        # Rebuild parent tree from doc_elem's children
        self._build_parent_tree(parent_tree, doc_elem, pdf)

        return ProcessorResult(
            processor_name=self.name,
            changes_made=total_mcids,
        )

    @staticmethod
    def _ensure_tabs(pdf: pikepdf.Pdf) -> int:
        """Set /Tabs /S on every page that lacks it. Returns count of pages fixed."""
        count = 0
        for page in pdf.pages:
            if "/Tabs" not in page:
                page["/Tabs"] = pikepdf.Name("/S")
                count += 1
        return count

    def _is_already_tagged(self, pdf: pikepdf.Pdf) -> bool:
        """Check if the PDF already has a populated tag tree."""
        if "/StructTreeRoot" not in pdf.Root:
            return False
        root = pdf.Root["/StructTreeRoot"]
        if "/K" not in root:
            return False
        kids = root["/K"]
        if isinstance(kids, pikepdf.Array) and len(kids) == 0:
            return False
        return True

    def _tag_page(
        self,
        pdf: pikepdf.Pdf,
        page: pikepdf.Dictionary,
        doc_elem: pikepdf.Object,
        page_idx: int,
    ) -> int:
        """Wrap text content on a page in marked content and create /P elems."""
        if "/Contents" not in page:
            return 0

        # Parse the content stream
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            logger.debug("Could not parse content stream for page %d", page_idx)
            return 0

        new_ops: list[tuple[list[pikepdf.Object], pikepdf.Operator]] = []
        mcid = 0
        in_text = False
        text_ops_buffer: list[tuple[list[pikepdf.Object], pikepdf.Operator]] = []
        text_show_ops = {
            pikepdf.Operator("Tj"),
            pikepdf.Operator("TJ"),
            pikepdf.Operator("'"),
            pikepdf.Operator('"'),
        }

        for operands, operator in ops:
            if operator == pikepdf.Operator("BT"):
                in_text = True
                text_ops_buffer = [(operands, operator)]
                continue

            if operator == pikepdf.Operator("ET") and in_text:
                text_ops_buffer.append((operands, operator))

                # Check if this BT/ET block has any text-showing operators
                has_text = any(op in text_show_ops for _, op in text_ops_buffer)
                if has_text:
                    # Wrap entire BT/ET block in BDC/EMC
                    new_ops.append((
                        [pikepdf.Name("/P"), pikepdf.Dictionary({"/MCID": mcid})],
                        pikepdf.Operator("BDC"),
                    ))
                    new_ops.extend(text_ops_buffer)
                    new_ops.append(([], pikepdf.Operator("EMC")))

                    # Create /P structure element
                    p_elem = make_struct_elem(
                        pdf, "P", doc_elem, page=page, mcid=mcid
                    )
                    add_kid(doc_elem, p_elem)
                    mcid += 1
                else:
                    new_ops.extend(text_ops_buffer)

                in_text = False
                text_ops_buffer = []
                continue

            if in_text:
                text_ops_buffer.append((operands, operator))
            else:
                new_ops.append((operands, operator))

        # Replace the content stream
        if mcid > 0:
            new_content = pikepdf.unparse_content_stream(new_ops)
            page["/Contents"] = pdf.make_stream(new_content)

        return mcid

    def _build_parent_tree(
        self,
        parent_tree: pikepdf.Dictionary,
        doc_elem: pikepdf.Object,
        pdf: pikepdf.Pdf,
    ) -> None:
        """Build the ParentTree number tree from structure elements."""
        # Group struct elems by page StructParents index
        page_map: dict[int, list[pikepdf.Object]] = {}

        if "/K" not in doc_elem:
            return

        kids = doc_elem["/K"]
        if not isinstance(kids, pikepdf.Array):
            kids = pikepdf.Array([kids])

        for kid in kids:
            if not isinstance(kid, pikepdf.Dictionary):
                continue
            if "/Pg" in kid:
                page_ref = kid["/Pg"]
                # Find the page index
                for idx, page in enumerate(pdf.pages):
                    if page.objgen == page_ref.objgen:
                        if idx not in page_map:
                            page_map[idx] = []
                        page_map[idx].append(kid)
                        break

        nums = pikepdf.Array()
        for page_idx in sorted(page_map.keys()):
            elems = page_map[page_idx]
            nums.append(page_idx)
            nums.append(pdf.make_indirect(pikepdf.Array(elems)))

        parent_tree["/Nums"] = nums
