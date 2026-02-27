"""Tests for TaggerProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf
import pytest

from accesspdf.processors.tagger import TaggerProcessor
from tests.utils.validate import count_tags_by_type, validate_tag_tree


class TestTaggerProcessor:
    def _run_tagger(self, src: Path, out: Path) -> None:
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            proc = TaggerProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_tags_untagged_pdf(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        assert self.result.success is True
        assert self.result.changes_made > 0

        with pikepdf.open(output_pdf) as pdf:
            assert "/StructTreeRoot" in pdf.Root

    def test_creates_mark_info(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            assert "/MarkInfo" in pdf.Root
            assert bool(pdf.Root["/MarkInfo"]["/Marked"]) is True

    def test_creates_document_root(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            root = pdf.Root["/StructTreeRoot"]
            kids = root["/K"]
            # Should have a /Document element
            if isinstance(kids, pikepdf.Array):
                doc = kids[0]
            else:
                doc = kids
            assert str(doc["/S"]) == "/Document"

    def test_creates_paragraph_tags(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        counts = count_tags_by_type(output_pdf)
        assert "Document" in counts
        assert "P" in counts
        assert counts["P"] >= 1

    def test_tag_tree_valid(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        result = validate_tag_tree(output_pdf)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_idempotent(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        first_changes = self.result.changes_made

        # Run again on already-tagged output
        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            proc = TaggerProcessor()
            result2 = proc.process(pdf)
            pdf.save(output_pdf)

        assert result2.changes_made == 0

    def test_output_is_valid_pdf(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_tagger(simple_pdf, output_pdf)
        # Should be openable without errors
        with pikepdf.open(output_pdf) as pdf:
            assert len(pdf.pages) > 0
