"""Tests for TablesProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf

from accesspdf.processors.tables import TablesProcessor
from accesspdf.processors.tagger import TaggerProcessor
from tests.utils.validate import count_tags_by_type


class TestTablesProcessor:
    def _run(self, src: Path, out: Path) -> None:
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            proc = TablesProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_detects_table(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        assert self.result.success is True
        assert self.result.changes_made > 0

    def test_creates_table_structure(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        assert counts.get("Table", 0) >= 1
        assert counts.get("TR", 0) >= 2  # at least header + 1 data row

    def test_header_row_tagged(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        assert counts.get("TH", 0) >= 1

    def test_no_tables_in_simple(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run(simple_pdf, output_pdf)
        assert self.result.changes_made == 0

    def test_idempotent(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = TablesProcessor().process(pdf)
            pdf.save(output_pdf)

        assert result2.changes_made == 0
