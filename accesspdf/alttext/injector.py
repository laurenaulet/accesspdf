"""Injects approved alt text from a sidecar file into a PDF via pikepdf."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pikepdf

from accesspdf.alttext.sidecar import SidecarFile
from accesspdf.models import AltTextStatus
from accesspdf.processors._pdf_helpers import add_kid, make_struct_elem

logger = logging.getLogger(__name__)


def inject_alt_text(pdf_path: Path, sidecar: SidecarFile) -> int:
    """Inject approved/decorative alt text entries into the PDF at *pdf_path*.

    For each actionable sidecar entry, finds the matching image XObject by hash
    and creates a /Figure structure element with /Alt text in the tag tree,
    properly linked to the image via marked content (BDC/EMC + MCID).

    Returns the number of entries injected.
    """
    actionable = [e for e in sidecar.images if e.is_actionable]
    if not actionable:
        logger.info("No approved or decorative alt text entries to inject.")
        return 0

    count = 0
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            logger.warning("PDF has no structure tree -- cannot inject alt text.")
            return 0

        # Build lookup: hash -> (alt_text, is_decorative)
        entry_lookup: dict[str, tuple[str, bool]] = {}
        for entry in actionable:
            is_deco = entry.status == AltTextStatus.DECORATIVE
            entry_lookup[entry.hash] = (entry.alt_text, is_deco)

        # First pass: update existing /Figure tags (e.g. from PowerPoint exports)
        struct_root = pdf.Root["/StructTreeRoot"]
        count += _update_existing_figures(struct_root, entry_lookup, pdf)

        # Second pass: create new /Figure tags with marked content for remaining
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
    """Walk the structure tree updating any existing /Figure tags with /Alt."""
    count = 0
    try:
        if "/S" in node and str(node["/S"]) == "/Figure":
            if "/Alt" not in node or not str(node["/Alt"]).strip():
                page_idx = _get_page_index(node, pdf)
                if page_idx is not None:
                    img_hash = _match_page_image(pdf, page_idx, entry_lookup)
                    if img_hash is not None:
                        alt_text, is_deco = entry_lookup[img_hash]
                        if is_deco:
                            node[pikepdf.Name("/Alt")] = pikepdf.String("")
                            node[pikepdf.Name("/ActualText")] = pikepdf.String("")
                        else:
                            node[pikepdf.Name("/Alt")] = pikepdf.String(alt_text)
                        del entry_lookup[img_hash]
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
    """Create /Figure elements linked to images via BDC/EMC marked content."""
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

        page_obj = page.obj if hasattr(page, "obj") else page

        # Build XObject name -> hash mapping for this page
        name_hash_map = _get_page_image_name_hashes(page)
        if not name_hash_map:
            continue

        # Find which images on this page need tagging
        to_tag: list[tuple[str, str]] = []
        for xobj_name, img_hash in name_hash_map.items():
            if img_hash in entry_lookup:
                to_tag.append((xobj_name, img_hash))
        if not to_tag:
            continue

        # Find the next available MCID on this page
        mcid = _get_next_mcid(page)

        # Parse content stream
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:
            logger.debug("Could not parse content stream for page %d", page_idx)
            continue

        # Wrap matching Do commands with BDC/EMC marked content
        new_ops: list[tuple[list, pikepdf.Operator]] = []
        tagged_names: set[str] = set()

        for operands, operator in ops:
            if operator == pikepdf.Operator("Do") and len(operands) == 1:
                do_name = str(operands[0])
                matched = None
                for xobj_name, img_hash in to_tag:
                    if do_name == f"/{xobj_name}" or do_name == xobj_name:
                        if xobj_name not in tagged_names:
                            matched = (xobj_name, img_hash)
                            break

                if matched:
                    xobj_name, img_hash = matched
                    alt_text, is_deco = entry_lookup[img_hash]

                    # BDC ... Do ... EMC
                    new_ops.append((
                        [pikepdf.Name("/Figure"),
                         pikepdf.Dictionary({"/MCID": mcid})],
                        pikepdf.Operator("BDC"),
                    ))
                    new_ops.append((operands, operator))
                    new_ops.append(([], pikepdf.Operator("EMC")))

                    # Create /Figure structure element linked via MCID
                    figure = make_struct_elem(
                        pdf, "Figure", doc_elem,
                        page=page_obj, mcid=mcid,
                        alt="" if is_deco else alt_text,
                    )
                    if is_deco:
                        figure[pikepdf.Name("/ActualText")] = pikepdf.String("")
                    add_kid(doc_elem, figure)

                    tagged_names.add(xobj_name)
                    del entry_lookup[img_hash]
                    count += 1
                    mcid += 1
                else:
                    new_ops.append((operands, operator))
            else:
                new_ops.append((operands, operator))

        # Replace content stream if we tagged any images
        if tagged_names:
            try:
                new_content = pikepdf.unparse_content_stream(new_ops)
                page["/Contents"] = pdf.make_stream(new_content)
            except Exception:
                logger.debug("Could not rewrite content stream for page %d", page_idx)

    # Rebuild parent tree to include the new Figure elements
    _rebuild_parent_tree(pdf)

    return count


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_page_image_name_hashes(page: pikepdf.Page) -> dict[str, str]:
    """Get XObject name -> md5 hash mapping for image XObjects on a page."""
    result: dict[str, str] = {}
    if "/Resources" not in page or "/XObject" not in page["/Resources"]:
        return result
    for name, xobj_ref in page["/Resources"]["/XObject"].items():
        try:
            xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
            if not isinstance(xobj, pikepdf.Stream):
                continue
            if str(xobj.get("/Subtype", "")) == "/Image":
                raw = bytes(xobj.read_raw_bytes())
                result[name] = hashlib.md5(raw).hexdigest()
        except Exception:
            pass
    return result


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


def _get_next_mcid(page: pikepdf.Object) -> int:
    """Find the next available MCID on a page by scanning the content stream."""
    max_mcid = -1
    try:
        ops = pikepdf.parse_content_stream(page)
        for operands, operator in ops:
            if operator == pikepdf.Operator("BDC") and len(operands) >= 2:
                props = operands[1]
                if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                    mcid_val = int(props["/MCID"])
                    if mcid_val > max_mcid:
                        max_mcid = mcid_val
    except Exception:
        pass
    return max_mcid + 1


def _rebuild_parent_tree(pdf: pikepdf.Pdf) -> None:
    """Merge new structure elements into the existing ParentTree.

    Instead of rebuilding from scratch (which would destroy existing /P
    paragraph mappings), this reads the current ParentTree, then walks the
    document element's children to find any structure elements whose MCIDs
    are not yet represented, and inserts them into the correct slots.
    """
    struct_root = pdf.Root["/StructTreeRoot"]

    doc_elem = None
    if "/K" in struct_root:
        kids = struct_root["/K"]
        if isinstance(kids, pikepdf.Array) and len(kids) > 0:
            doc_elem = kids[0]
        elif isinstance(kids, pikepdf.Dictionary):
            doc_elem = kids
    if doc_elem is None:
        return

    # ── 1. Read existing ParentTree into a mutable dict ──────────────
    parent_tree = struct_root.get("/ParentTree")
    if parent_tree is None:
        parent_tree = pdf.make_indirect(pikepdf.Dictionary({
            "/Nums": pikepdf.Array(),
        }))
        struct_root["/ParentTree"] = parent_tree

    existing_nums = parent_tree.get("/Nums")
    # Parse existing /Nums into {page_idx: list[elem_or_null]}
    page_arrays: dict[int, list] = {}
    if existing_nums and isinstance(existing_nums, pikepdf.Array):
        i = 0
        while i + 1 < len(existing_nums):
            try:
                pg_idx = int(existing_nums[i])
                arr_obj = existing_nums[i + 1]
                if hasattr(arr_obj, "resolve"):
                    arr_obj = arr_obj.resolve()
                if isinstance(arr_obj, pikepdf.Array):
                    page_arrays[pg_idx] = list(arr_obj)
            except Exception:
                pass
            i += 2

    # ── 2. Walk doc_elem children and merge new entries ──────────────
    if "/K" not in doc_elem:
        return

    all_kids = doc_elem["/K"]
    if not isinstance(all_kids, pikepdf.Array):
        all_kids = pikepdf.Array([all_kids])

    for kid in all_kids:
        if not isinstance(kid, pikepdf.Dictionary):
            continue
        if "/Pg" not in kid or "/K" not in kid:
            continue

        k_val = kid["/K"]
        mcids: list[int] = []
        if isinstance(k_val, pikepdf.Array):
            for item in k_val:
                try:
                    mcids.append(int(item))
                except (TypeError, ValueError):
                    pass
        else:
            try:
                mcids.append(int(k_val))
            except (TypeError, ValueError):
                pass

        if not mcids:
            continue

        page_ref = kid["/Pg"]
        for idx, pg in enumerate(pdf.pages):
            pg_obj = pg.obj if hasattr(pg, "obj") else pg
            try:
                if pg_obj.objgen == page_ref.objgen:
                    if idx not in page_arrays:
                        page_arrays[idx] = []
                    arr = page_arrays[idx]
                    for m in mcids:
                        # Grow the array if needed
                        while len(arr) <= m:
                            arr.append(None)
                        # Only fill empty slots -- don't overwrite existing entries
                        if arr[m] is None:
                            arr[m] = kid
                    break
            except Exception:
                pass

    # ── 3. Write back, using pikepdf.Null() for empty slots ──────────
    nums = pikepdf.Array()
    for page_idx in sorted(page_arrays.keys()):
        arr = page_arrays[page_idx]
        pdf_arr = pikepdf.Array()
        for elem in arr:
            if elem is None:
                pdf_arr.append(pikepdf.Null())
            else:
                pdf_arr.append(elem)
        nums.append(page_idx)
        nums.append(pdf.make_indirect(pdf_arr))

    parent_tree["/Nums"] = nums


def _match_page_image(
    pdf: pikepdf.Pdf,
    page_idx: int,
    entry_lookup: dict[str, tuple[str, bool]],
) -> str | None:
    """Try to match an image on a page to an entry. Returns the hash or None."""
    if page_idx >= len(pdf.pages):
        return None
    page = pdf.pages[page_idx]
    hashes = _get_page_image_hashes(page)
    for img_hash in hashes:
        if img_hash in entry_lookup:
            return img_hash
    return None


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
