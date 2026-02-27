"""Final PDF output writer.

The writer takes an already-remediated PDF and performs final output tasks
such as setting the PDF/UA identifier and writing display-title preference.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pikepdf

logger = logging.getLogger(__name__)


def finalize_output(pdf_path: Path) -> None:
    """Apply final output fixes to a remediated PDF.

    Called as the last step after all processors and alt text injection.
    """
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        _set_display_title(pdf)
        pdf.save(pdf_path)


def _set_display_title(pdf: pikepdf.Pdf) -> None:
    """Set ViewerPreferences to display the document title in the title bar."""
    if "/ViewerPreferences" not in pdf.Root:
        pdf.Root["/ViewerPreferences"] = pikepdf.Dictionary()

    pdf.Root["/ViewerPreferences"]["/DisplayDocTitle"] = True
