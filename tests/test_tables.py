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

    def test_th_has_id(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            from accesspdf.processors._pdf_helpers import walk_struct_tree
            elems = walk_struct_tree(pdf.Root["/StructTreeRoot"])
            th_elems = [e for e in elems if str(e.get("/S", "")) == "/TH"]
            assert len(th_elems) >= 1
            for th in th_elems:
                assert "/ID" in th, "TH cells should have an /ID attribute"

    def test_th_has_scope(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            from accesspdf.processors._pdf_helpers import walk_struct_tree
            elems = walk_struct_tree(pdf.Root["/StructTreeRoot"])
            th_elems = [e for e in elems if str(e.get("/S", "")) == "/TH"]
            for th in th_elems:
                assert "/A" in th, "TH cells should have /A attribute dict"
                assert str(th["/A"].get("/Scope", "")) == "/Column"

    def test_td_has_headers(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            from accesspdf.processors._pdf_helpers import walk_struct_tree
            elems = walk_struct_tree(pdf.Root["/StructTreeRoot"])
            td_elems = [e for e in elems if str(e.get("/S", "")) == "/TD"]
            assert len(td_elems) >= 1
            for td in td_elems:
                assert "/Headers" in td, "TD cells should have /Headers referencing column TH"

    def test_idempotent(self, tables_pdf: Path, output_pdf: Path) -> None:
        self._run(tables_pdf, output_pdf)

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = TablesProcessor().process(pdf)
            pdf.save(output_pdf)

        assert result2.changes_made == 0
