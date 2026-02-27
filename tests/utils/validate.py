"""Tag tree validation utilities for test assertions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pikepdf


@dataclass
class ValidationResult:
    """Result of tag tree validation."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tag_count: int = 0


def validate_tag_tree(pdf_path: Path) -> ValidationResult:
    """Validate that a PDF's tag tree is well-formed."""
    result = ValidationResult()

    with pikepdf.open(pdf_path) as pdf:
        # 1. StructTreeRoot exists
        if "/StructTreeRoot" not in pdf.Root:
            result.valid = False
            result.errors.append("No StructTreeRoot found.")
            return result

        struct_root = pdf.Root["/StructTreeRoot"]

        # 2. /K (kids) is present
        if "/K" not in struct_root:
            result.valid = False
            result.errors.append("StructTreeRoot has no /K (children).")
            return result

        # 3. MarkInfo exists with /Marked = true
        if "/MarkInfo" not in pdf.Root:
            result.warnings.append("No MarkInfo dictionary.")
        else:
            mark_info = pdf.Root["/MarkInfo"]
            if "/Marked" not in mark_info or not bool(mark_info["/Marked"]):
                result.warnings.append("MarkInfo.Marked is not true.")

        # 4. Walk and validate structure elements
        _walk_validate(struct_root["/K"], struct_root, result)

    return result


def _walk_validate(
    node: pikepdf.Object, parent: pikepdf.Object, result: ValidationResult
) -> None:
    """Recursively validate structure elements."""
    if isinstance(node, pikepdf.Array):
        for child in node:
            if isinstance(child, pikepdf.Dictionary):
                _walk_validate(child, parent, result)
            # Integer children are MCIDs — valid leaf nodes
        return

    if not isinstance(node, pikepdf.Dictionary):
        return

    # Check for /Type if present (should be /StructElem for non-root)
    if "/S" in node:
        result.tag_count += 1

        # Every struct elem should have /P (parent)
        if "/P" not in node:
            result.warnings.append(
                f"Structure element {str(node.get('/S', '?'))} missing /P (parent)."
            )

    # Recurse into children
    if "/K" in node:
        kids = node["/K"]
        if isinstance(kids, pikepdf.Array):
            for child in kids:
                if isinstance(child, pikepdf.Dictionary):
                    _walk_validate(child, node, result)
        elif isinstance(kids, pikepdf.Dictionary):
            _walk_validate(kids, node, result)


def count_tags_by_type(pdf_path: Path) -> dict[str, int]:
    """Count structure elements by tag type."""
    counts: dict[str, int] = {}

    with pikepdf.open(pdf_path) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            return counts
        struct_root = pdf.Root["/StructTreeRoot"]
        if "/K" in struct_root:
            _count_walk(struct_root["/K"], counts)

    return counts


def _count_walk(node: pikepdf.Object, counts: dict[str, int]) -> None:
    """Walk the tree and count tags."""
    if isinstance(node, pikepdf.Array):
        for child in node:
            if isinstance(child, pikepdf.Dictionary):
                _count_walk(child, counts)
        return

    if not isinstance(node, pikepdf.Dictionary):
        return

    if "/S" in node:
        tag = str(node["/S"])[1:]  # strip leading /
        counts[tag] = counts.get(tag, 0) + 1

    if "/K" in node:
        kids = node["/K"]
        if isinstance(kids, pikepdf.Array):
            for child in kids:
                if isinstance(child, pikepdf.Dictionary):
                    _count_walk(child, counts)
        elif isinstance(kids, pikepdf.Dictionary):
            _count_walk(kids, counts)
