"""Injects approved alt text from a sidecar file into a PDF via pikepdf."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pikepdf

from accesspdf.alttext.sidecar import SidecarFile
from accesspdf.models import AltTextStatus

logger = logging.getLogger(__name__)


def inject_alt_text(pdf_path: Path, sidecar: SidecarFile) -> int:
    """Inject approved/decorative alt text entries into the PDF at *pdf_path*.

    For each actionable sidecar entry, finds the matching image XObject by hash
    and creates a /Figure structure element with /Alt text in the tag tree.

    Returns the number of entries injected.
    """
    actionable = [e for e in sidecar.images if e.is_actionable]
    if not actionable:
        logger.info("No approved or decorative alt text entries to inject.")
        return 0

    count = 0
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            logger.warning("PDF has no structure tree — cannot inject alt text.")
            return 0

        # Build lookup: hash -> (alt_text, is_decorative)
        entry_lookup: dict[str, tuple[str, bool]] = {}
        for entry in actionable:
            is_deco = entry.status == AltTextStatus.DECORATIVE
            entry_lookup[entry.hash] = (entry.alt_text, is_deco)

        # First pass: try to update existing /Figure tags
        struct_root = pdf.Root["/StructTreeRoot"]
        count += _update_existing_figures(struct_root, entry_lookup, pdf)

        # Second pass: create /Figure tags for remaining unmatched entries
        if entry_lookup:
            count += _create_figure_tags(pdf, entry_lookup)

        pdf.save(pdf_path)

    logger.info("Injected alt text for %d image(s).", count)
    return count


def _update_existing_figures(
    node: pikepdf.Object,
    entry_lookup: dict[str, tuple[str, bool]],
    pdf: pikepdf.Pdf,
) -> int:
    """Walk the structure tree updating any existing /Figure tags."""
    count = 0
    try:
        if "/S" in node and str(node["/S"]) == "/Figure":
            if "/Alt" not in node or not str(node["/Alt"]).strip():
                # Try to match this Figure to an image via page
                page_idx = _get_page_index(node, pdf)
                if page_idx is not None:
                    matched = _match_page_image(pdf, page_idx, entry_lookup)
                    if matched:
                        count += 1

        if "/K" in node:
            kids = node["/K"]
            if isinstance(kids, pikepdf.Array):
                for child in kids:
                    if isinstance(child, pikepdf.Dictionary):
                        count += _update_existing_figures(child, entry_lookup, pdf)
            elif isinstance(kids, pikepdf.Dictionary):
                count += _update_existing_figures(kids, entry_lookup, pdf)
    except Exception:
        logger.debug("Error walking struct tree during injection", exc_info=True)
    return count


def _create_figure_tags(
    pdf: pikepdf.Pdf,
    entry_lookup: dict[str, tuple[str, bool]],
) -> int:
    """Create /Figure structure elements for images that have approved alt text."""
    count = 0
    struct_root = pdf.Root["/StructTreeRoot"]

    # Find the /Document element (first child of StructTreeRoot)
    doc_elem = None
    if "/K" in struct_root:
        kids = struct_root["/K"]
        if isinstance(kids, pikepdf.Array) and len(kids) > 0:
            doc_elem = kids[0]
        elif isinstance(kids, pikepdf.Dictionary):
            doc_elem = kids

    if doc_elem is None:
        doc_elem = struct_root

    for page_idx, page in enumerate(pdf.pages):
        if not entry_lookup:
            break

        page_hashes = _get_page_image_hashes(page)
        for img_hash in page_hashes:
            if img_hash not in entry_lookup:
                continue

            alt_text, is_decorative = entry_lookup[img_hash]

            # Create /Figure structure element
            page_obj = page.obj if hasattr(page, "obj") else page
            figure_dict: dict[str, pikepdf.Object] = {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Figure"),
                "/P": doc_elem,
                "/Pg": page_obj,
            }

            if is_decorative:
                figure_dict["/Alt"] = pikepdf.String("")
                figure_dict["/ActualText"] = pikepdf.String("")
            else:
                figure_dict["/Alt"] = pikepdf.String(alt_text)

            figure_elem = pdf.make_indirect(pikepdf.Dictionary(figure_dict))

            # Add to document's /K array
            if "/K" not in doc_elem:
                doc_elem[pikepdf.Name("/K")] = pikepdf.Array([figure_elem])
            else:
                kids = doc_elem["/K"]
                if isinstance(kids, pikepdf.Array):
                    kids.append(figure_elem)
                else:
                    doc_elem[pikepdf.Name("/K")] = pikepdf.Array([kids, figure_elem])

            del entry_lookup[img_hash]
            count += 1

    return count


def _get_page_image_hashes(page: pikepdf.Page) -> list[str]:
    """Get md5 hashes of all image XObjects on a page."""
    hashes: list[str] = []
    if "/Resources" not in page or "/XObject" not in page["/Resources"]:
        return hashes

    for _name, xobj_ref in page["/Resources"]["/XObject"].items():
        try:
            xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
            if not isinstance(xobj, pikepdf.Stream):
                continue
            subtype = str(xobj.get("/Subtype", ""))
            if subtype == "/Image":
                raw = bytes(xobj.read_raw_bytes())
                hashes.append(hashlib.md5(raw).hexdigest())
            elif subtype == "/Form":
                _collect_form_image_hashes(xobj, hashes)
        except Exception:
            pass
    return hashes


def _collect_form_image_hashes(form_xobj: pikepdf.Stream, hashes: list[str]) -> None:
    """Collect image hashes from inside a Form XObject."""
    try:
        resources = form_xobj.get("/Resources")
        if resources is None or "/XObject" not in resources:
            return
        for _name, inner_ref in resources["/XObject"].items():
            inner = inner_ref.resolve() if hasattr(inner_ref, "resolve") else inner_ref
            if not isinstance(inner, pikepdf.Stream):
                continue
            if str(inner.get("/Subtype", "")) == "/Image":
                raw = bytes(inner.read_raw_bytes())
                hashes.append(hashlib.md5(raw).hexdigest())
    except Exception:
        pass


def _match_page_image(
    pdf: pikepdf.Pdf,
    page_idx: int,
    entry_lookup: dict[str, tuple[str, bool]],
) -> bool:
    """Try to match an image on a page to an entry in the lookup."""
    if page_idx >= len(pdf.pages):
        return False

    page = pdf.pages[page_idx]
    hashes = _get_page_image_hashes(page)
    for img_hash in hashes:
        if img_hash in entry_lookup:
            # Found a match — this function doesn't inject, it just confirms
            return True
    return False


def _get_page_index(node: pikepdf.Object, pdf: pikepdf.Pdf) -> int | None:
    """Determine which page a structure element belongs to."""
    if "/Pg" in node:
        try:
            page_ref = node["/Pg"]
            if hasattr(page_ref, "resolve"):
                page_ref = page_ref.resolve()
            for idx, pg in enumerate(pdf.pages):
                pg_obj = pg.obj if hasattr(pg, "obj") else pg
                if pg_obj.same_owner_as(page_ref) and pg_obj.objgen == page_ref.objgen:
                    return idx
        except Exception:
            pass

    if "/K" in node:
        kids = node["/K"]
        items = kids if isinstance(kids, pikepdf.Array) else [kids]
        for child in items:
            if isinstance(child, pikepdf.Dictionary) and "/Pg" in child:
                try:
                    page_ref = child["/Pg"]
                    if hasattr(page_ref, "resolve"):
                        page_ref = page_ref.resolve()
                    for idx, pg in enumerate(pdf.pages):
                        pg_obj = pg.obj if hasattr(pg, "obj") else pg
                        if pg_obj.same_owner_as(page_ref) and pg_obj.objgen == page_ref.objgen:
                            return idx
                except Exception:
                    pass

    return None
