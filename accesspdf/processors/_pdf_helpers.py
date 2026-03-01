"""Low-level PDF structure helpers shared across processors."""

from __future__ import annotations

import pikepdf


def ensure_struct_tree_root(pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    """Return StructTreeRoot, creating it if absent."""
    if "/StructTreeRoot" in pdf.Root:
        root = pdf.Root["/StructTreeRoot"]
    else:
        root = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructTreeRoot"),
            "/K": pikepdf.Array(),
            "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({
                "/Nums": pikepdf.Array(),
            })),
        }))
        pdf.Root["/StructTreeRoot"] = root

    # Ensure /RoleMap exists (PDF/UA requires it, even if empty)
    if "/RoleMap" not in root:
        root["/RoleMap"] = pikepdf.Dictionary()

    return root


def ensure_mark_info(pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    """Return MarkInfo dict, creating if absent. Sets /Marked = true."""
    if "/MarkInfo" not in pdf.Root:
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary()

    mark_info = pdf.Root["/MarkInfo"]
    mark_info["/Marked"] = True
    return mark_info


def ensure_parent_tree(struct_root: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    """Return ParentTree, creating if absent."""
    if "/ParentTree" in struct_root:
        return struct_root["/ParentTree"]

    parent_tree = pdf.make_indirect(pikepdf.Dictionary({
        "/Nums": pikepdf.Array(),
    }))
    struct_root["/ParentTree"] = parent_tree
    return parent_tree


def make_struct_elem(
    pdf: pikepdf.Pdf,
    tag: str,
    parent: pikepdf.Object,
    *,
    page: pikepdf.Object | None = None,
    mcid: int | None = None,
    alt: str | None = None,
) -> pikepdf.Object:
    """Create an indirect structure element and return it.

    Parameters
    ----------
    tag : e.g. "Document", "P", "H1", "Table"
    parent : parent structure element (or StructTreeRoot)
    page : optional page object reference
    mcid : optional marked content ID (creates integer kid)
    alt : optional /Alt text
    """
    # Unwrap ObjectHelper (e.g. Page objects) to raw pikepdf.Object
    raw_parent = parent.obj if hasattr(parent, "obj") else parent
    raw_page = page.obj if (page is not None and hasattr(page, "obj")) else page

    elem_dict: dict[str, pikepdf.Object] = {
        "/S": pikepdf.Name(f"/{tag}"),
        "/P": raw_parent,
        "/K": pikepdf.Array(),
    }
    if raw_page is not None:
        elem_dict["/Pg"] = raw_page
    if alt is not None:
        elem_dict["/Alt"] = pikepdf.String(alt)

    elem = pdf.make_indirect(pikepdf.Dictionary(elem_dict))

    if mcid is not None:
        elem["/K"] = pikepdf.Array([mcid])

    return elem


def add_kid(parent: pikepdf.Object, child: pikepdf.Object) -> None:
    """Append *child* to *parent*'s /K array."""
    if "/K" not in parent:
        parent["/K"] = pikepdf.Array()
    kids = parent["/K"]
    if isinstance(kids, pikepdf.Array):
        kids.append(child)
    else:
        # Single kid — convert to array
        parent["/K"] = pikepdf.Array([kids, child])


def get_struct_tree_kids(struct_root: pikepdf.Dictionary) -> list[pikepdf.Object]:
    """Get the top-level children of StructTreeRoot as a list."""
    if "/K" not in struct_root:
        return []
    kids = struct_root["/K"]
    if isinstance(kids, pikepdf.Array):
        return list(kids)
    return [kids]


def walk_struct_tree(node: pikepdf.Object) -> list[pikepdf.Object]:
    """Yield all structure element descendants (depth-first)."""
    elements: list[pikepdf.Object] = []
    _walk(node, elements)
    return elements


def _walk(node: pikepdf.Object, elements: list[pikepdf.Object]) -> None:
    if not isinstance(node, pikepdf.Dictionary):
        return
    if "/S" in node:
        elements.append(node)
    if "/K" in node:
        kids = node["/K"]
        if isinstance(kids, pikepdf.Array):
            for child in kids:
                if isinstance(child, pikepdf.Dictionary):
                    _walk(child, elements)
        elif isinstance(kids, pikepdf.Dictionary):
            _walk(kids, elements)
