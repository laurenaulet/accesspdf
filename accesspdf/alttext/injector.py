"""Injects approved alt text from a sidecar file into a PDF via pikepdf."""

from __future__ import annotations

import logging
from pathlib import Path

import pikepdf

from accesspdf.alttext.sidecar import SidecarFile
from accesspdf.models import AltTextStatus

logger = logging.getLogger(__name__)


def inject_alt_text(pdf_path: Path, sidecar: SidecarFile) -> int:
    """Inject approved alt text entries into the PDF at *pdf_path*.

    Returns the number of entries injected.
    """
    approved = [e for e in sidecar.images if e.status == AltTextStatus.APPROVED]
    if not approved:
        logger.info("No approved alt text entries to inject.")
        return 0

    count = 0
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            logger.warning("PDF has no structure tree — cannot inject alt text.")
            return 0

        # Build a lookup: hash -> alt_text
        alt_lookup: dict[str, str] = {e.hash: e.alt_text for e in approved}

        # Walk the structure tree and match Figure tags
        struct_root = pdf.Root["/StructTreeRoot"]
        count = _walk_and_inject(struct_root, alt_lookup, pdf)
        pdf.save(pdf_path)

    logger.info("Injected alt text for %d image(s).", count)
    return count


def _walk_and_inject(
    node: pikepdf.Object, alt_lookup: dict[str, str], pdf: pikepdf.Pdf
) -> int:
    """Recursively walk structure tree, injecting /Alt on matched Figure tags."""
    count = 0
    try:
        if "/S" in node and str(node["/S"]) == "/Figure":
            # Phase 1+ will implement hash-based matching.
            # For now, this is a skeleton that walks the tree.
            pass

        if "/K" in node:
            kids = node["/K"]
            if isinstance(kids, pikepdf.Array):
                for child in kids:
                    if isinstance(child, pikepdf.Dictionary):
                        count += _walk_and_inject(child, alt_lookup, pdf)
            elif isinstance(kids, pikepdf.Dictionary):
                count += _walk_and_inject(kids, alt_lookup, pdf)
    except Exception:
        logger.debug("Error walking struct tree during injection", exc_info=True)

    return count
