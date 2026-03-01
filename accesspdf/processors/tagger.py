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
            changes = self._ensure_tabs(pdf)
            # Also add /Figure tags for any untagged images
            changes += self._tag_untagged_images(pdf)
            return ProcessorResult(processor_name=self.name, changes_made=changes)

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

    def _tag_untagged_images(self, pdf: pikepdf.Pdf) -> int:
        """Add /Figure tags for images not already wrapped in BDC/EMC.

        This handles PDFs that were tagged by an older version of the tool
        (or another tool) that didn't create Figure tags for images.
        """
        struct_root = pdf.Root.get("/StructTreeRoot")
        if struct_root is None:
            return 0

        # Find the /Document element to append Figure kids to
        doc_elem = None
        if "/K" in struct_root:
            kids = struct_root["/K"]
            if isinstance(kids, pikepdf.Array) and len(kids) > 0:
                doc_elem = kids[0]
            elif isinstance(kids, pikepdf.Dictionary):
                doc_elem = kids
        if doc_elem is None:
            doc_elem = struct_root

        count = 0
        for page_idx, page in enumerate(pdf.pages):
            image_names = self._get_image_xobj_names(page)
            if not image_names:
                continue

            try:
                ops = pikepdf.parse_content_stream(page)
            except Exception:
                continue

            # Find which image Do ops are already inside BDC/EMC
            already_tagged: set[str] = set()
            bdc_depth = 0
            for operands, operator in ops:
                if operator == pikepdf.Operator("BDC"):
                    bdc_depth += 1
                elif operator == pikepdf.Operator("EMC"):
                    bdc_depth = max(0, bdc_depth - 1)
                elif (
                    operator == pikepdf.Operator("Do")
                    and bdc_depth > 0
                    and len(operands) == 1
                    and str(operands[0]) in image_names
                ):
                    already_tagged.add(str(operands[0]))

            untagged = image_names - already_tagged
            if not untagged:
                continue

            # Find next available MCID on this page
            mcid = 0
            for operands, operator in ops:
                if operator == pikepdf.Operator("BDC") and len(operands) >= 2:
                    props = operands[1]
                    if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                        mcid = max(mcid, int(props["/MCID"]) + 1)

            # Wrap untagged image Do ops in BDC/EMC
            page_obj = page.obj if hasattr(page, "obj") else page
            new_ops: list[tuple[list, pikepdf.Operator]] = []
            for operands, operator in ops:
                if (
                    operator == pikepdf.Operator("Do")
                    and len(operands) == 1
                    and str(operands[0]) in untagged
                ):
                    new_ops.append((
                        [pikepdf.Name("/Figure"),
                         pikepdf.Dictionary({"/MCID": mcid})],
                        pikepdf.Operator("BDC"),
                    ))
                    new_ops.append((operands, operator))
                    new_ops.append(([], pikepdf.Operator("EMC")))

                    fig_elem = make_struct_elem(
                        pdf, "Figure", doc_elem, page=page_obj, mcid=mcid
                    )
                    add_kid(doc_elem, fig_elem)
                    untagged.discard(str(operands[0]))
                    count += 1
                    mcid += 1
                else:
                    new_ops.append((operands, operator))

            try:
                new_content = pikepdf.unparse_content_stream(new_ops)
                page["/Contents"] = pdf.make_stream(new_content)
            except Exception:
                logger.debug("Could not rewrite content stream for page %d", page_idx)

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
        """Wrap text and image content on a page in marked content."""
        if "/Contents" not in page:
            return 0

        # Parse the content stream
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            logger.debug("Could not parse content stream for page %d", page_idx)
            return 0

        # Build set of image XObject names on this page
        image_names = self._get_image_xobj_names(page)

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
            # Tag image Do operators as /Figure
            elif (
                operator == pikepdf.Operator("Do")
                and len(operands) == 1
                and str(operands[0]) in image_names
            ):
                new_ops.append((
                    [pikepdf.Name("/Figure"), pikepdf.Dictionary({"/MCID": mcid})],
                    pikepdf.Operator("BDC"),
                ))
                new_ops.append((operands, operator))
                new_ops.append(([], pikepdf.Operator("EMC")))

                fig_elem = make_struct_elem(
                    pdf, "Figure", doc_elem, page=page, mcid=mcid
                )
                add_kid(doc_elem, fig_elem)
                mcid += 1
            else:
                new_ops.append((operands, operator))

        # Replace the content stream
        if mcid > 0:
            new_content = pikepdf.unparse_content_stream(new_ops)
            page["/Contents"] = pdf.make_stream(new_content)

        return mcid

    @staticmethod
    def _get_image_xobj_names(page: pikepdf.Dictionary) -> set[str]:
        """Return set of XObject names (e.g. '/Im0') that are images."""
        names: set[str] = set()
        try:
            resources = page.get("/Resources")
            if resources is None or "/XObject" not in resources:
                return names
            for name, xobj_ref in resources["/XObject"].items():
                xobj = xobj_ref
                if hasattr(xobj, "resolve"):
                    xobj = xobj.resolve()
                if isinstance(xobj, pikepdf.Stream):
                    if str(xobj.get("/Subtype", "")) == "/Image":
                        # pikepdf dict keys may or may not include leading /
                        key = name if name.startswith("/") else f"/{name}"
                        names.add(key)
        except Exception:
            logger.debug("Could not enumerate image XObjects")
        return names

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
