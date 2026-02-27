"""Tests for HeadingsProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf

from accesspdf.processors.headings import HeadingsProcessor
from accesspdf.processors.tagger import TaggerProcessor
from tests.utils.validate import count_tags_by_type


class TestHeadingsProcessor:
    def _run(self, src: Path, out: Path) -> None:
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            proc = HeadingsProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_identifies_headings(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        assert self.result.success is True
        assert self.result.changes_made > 0

    def test_creates_heading_tags(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        # Should have at least one heading tag
        heading_count = sum(counts.get(f"H{i}", 0) for i in range(1, 7))
        assert heading_count > 0

    def test_body_text_not_promoted(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        # Should still have /P tags for body text
        assert counts.get("P", 0) > 0

    def test_no_headings_in_simple_pdf(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run(simple_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        heading_count = sum(counts.get(f"H{i}", 0) for i in range(1, 7))
        # simple.pdf has uniform font size — no headings expected
        assert heading_count == 0

    def test_idempotent(self, headings_pdf: Path, output_pdf: Path) -> None:
        self._run(headings_pdf, output_pdf)
        first_changes = self.result.changes_made

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = HeadingsProcessor().process(pdf)
            pdf.save(output_pdf)

        # Already promoted — should be 0 additional changes
        assert result2.changes_made == 0
