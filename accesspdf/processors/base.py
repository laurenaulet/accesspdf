"""Base protocol and utilities for remediation processors."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pikepdf

from accesspdf.models import ProcessorResult


@runtime_checkable
class Processor(Protocol):
    """Interface that every remediation processor must implement.

    Each processor addresses a single accessibility concern (tagging, metadata,
    headings, etc.).  Processors receive an open pikepdf.Pdf and mutate it
    in-place.  They must return a ProcessorResult describing what they did.
    """

    @property
    def name(self) -> str:
        """Human-readable processor name (e.g. 'TagStructure')."""
        ...

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        """Apply fixes to *pdf* and return a result summary.

        Implementations should catch their own expected exceptions and return
        a ProcessorResult with ``success=False`` plus the error message rather
        than raising.  Unexpected exceptions are allowed to propagate — the
        pipeline will catch them.
        """
        ...
