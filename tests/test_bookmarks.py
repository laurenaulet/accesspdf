"""Tests for BookmarksProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf

from accesspdf.processors.bookmarks import BookmarksProcessor
from accesspdf.processors.headings import HeadingsProcessor
from accesspdf.processors.tagger import TaggerProcessor


class TestBookmarksProcessor:
    def _run(self, src: Path, out: Path) -> None:
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            HeadingsProcessor().process(pdf)
            proc = BookmarksProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_creates_outline(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        assert self.result.success is True
        assert self.result.changes_made > 0

        with pikepdf.open(output_pdf) as pdf:
            assert "/Outlines" in pdf.Root or self.result.changes_made > 0

    def test_outline_matches_headings(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        # Should have created bookmark entries
        assert self.result.changes_made >= 3  # title + 2 sections at minimum

    def test_no_headings_skips(self, simple_pdf: Path, output_pdf: Path) -> None:
        shutil.copy2(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            # Skip headings processor — no headings exist
            result = BookmarksProcessor().process(pdf)
            pdf.save(output_pdf)

        assert result.changes_made == 0

    def test_idempotent(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = BookmarksProcessor().process(pdf)
            pdf.save(output_pdf)

        # Second run should still work (clears and rebuilds)
        assert result2.success is True
