"""LinksProcessor — tags hyperlink annotations with /Link structure elements."""

from __future__ import annotations

import logging

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import add_kid, make_struct_elem, walk_struct_tree

logger = logging.getLogger(__name__)


@register_processor
class LinksProcessor:
    @property
    def name(self) -> str:
        return "Links"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._process_links(pdf)
        except Exception as exc:
            logger.error("LinksProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _process_links(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        if "/StructTreeRoot" not in pdf.Root:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        struct_root = pdf.Root["/StructTreeRoot"]

        # Check if link tags already exist
        existing = walk_struct_tree(struct_root)
        has_links = any(str(e.get("/S", "")) == "/Link" for e in existing)
        if has_links:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        # Get the document element
        root_kids = struct_root["/K"]
        if isinstance(root_kids, pikepdf.Array) and len(root_kids) > 0:
            doc_elem = root_kids[0]
        elif isinstance(root_kids, pikepdf.Dictionary):
            doc_elem = root_kids
        else:
            return ProcessorResult(processor_name=self.name, changes_made=0)

        changes = 0

        for page_idx, page in enumerate(pdf.pages):
            if "/Annots" not in page:
                continue

            annots = page["/Annots"]
            if not isinstance(annots, pikepdf.Array):
                continue

            for annot in annots:
                if not isinstance(annot, pikepdf.Dictionary):
                    try:
                        annot = annot.resolve() if hasattr(annot, "resolve") else annot
                    except Exception:
                        continue
                    if not isinstance(annot, pikepdf.Dictionary):
                        continue

                subtype = annot.get("/Subtype")
                if subtype is None or str(subtype) != "/Link":
                    continue

                # Get the URI
                uri = self._get_link_uri(annot)
                alt_text = uri or "Link"

                # Create /Link structure element
                link_elem = make_struct_elem(
                    pdf, "Link", doc_elem, page=page, alt=alt_text
                )

                # Create OBJR (object reference) to the annotation
                # Unwrap ObjectHelper wrappers for pikepdf Dictionary construction
                raw_annot = annot.obj if hasattr(annot, "obj") else annot
                raw_page = page.obj if hasattr(page, "obj") else page
                objr = pdf.make_indirect(pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/OBJR"),
                    "/Obj": raw_annot,
                    "/Pg": raw_page,
                }))
                add_kid(link_elem, objr)
                add_kid(doc_elem, link_elem)
                changes += 1

        return ProcessorResult(processor_name=self.name, changes_made=changes)

    def _get_link_uri(self, annot: pikepdf.Dictionary) -> str:
        """Extract the URI from a link annotation."""
        # Check /A (action) dictionary
        if "/A" in annot:
            action = annot["/A"]
            if isinstance(action, pikepdf.Dictionary) and "/URI" in action:
                return str(action["/URI"])

        # Check /Dest (destination)
        if "/Dest" in annot:
            return f"internal:{annot['/Dest']}"

        return ""
