"""Tests for LinksProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf

from accesspdf.processors.links import LinksProcessor
from accesspdf.processors.tagger import TaggerProcessor
from tests.utils.validate import count_tags_by_type


class TestLinksProcessor:
    def _run(self, src: Path, out: Path) -> None:
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            proc = LinksProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_tags_hyperlinks(self, links_pdf: Path, output_pdf: Path) -> None:
        self._run(links_pdf, output_pdf)
        assert self.result.success is True
        assert self.result.changes_made >= 2  # 2 links in the test PDF

    def test_creates_link_structure(self, links_pdf: Path, output_pdf: Path) -> None:
        self._run(links_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        assert counts.get("Link", 0) >= 2

    def test_no_links_in_simple(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run(simple_pdf, output_pdf)
        assert self.result.changes_made == 0

    def test_idempotent(self, links_pdf: Path, output_pdf: Path) -> None:
        self._run(links_pdf, output_pdf)

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = LinksProcessor().process(pdf)
            pdf.save(output_pdf)

        assert result2.changes_made == 0
