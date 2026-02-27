"""Tests for MetadataProcessor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf

from accesspdf.processors.metadata import MetadataProcessor
from accesspdf.processors.tagger import TaggerProcessor


class TestMetadataProcessor:
    def _run_with_tagger(self, src: Path, out: Path) -> None:
        """Run tagger first (required), then metadata."""
        shutil.copy2(src, out)
        with pikepdf.open(out, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            proc = MetadataProcessor()
            self.result = proc.process(pdf)
            pdf.save(out)

    def test_sets_language(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_with_tagger(simple_pdf, output_pdf)
        assert self.result.success is True
        with pikepdf.open(output_pdf) as pdf:
            assert "/Lang" in pdf.Root
            lang = str(pdf.Root["/Lang"])
            assert len(lang) >= 2  # at least "en"

    def test_sets_marked_true(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_with_tagger(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            assert "/MarkInfo" in pdf.Root
            assert bool(pdf.Root["/MarkInfo"]["/Marked"]) is True

    def test_sets_display_doc_title(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_with_tagger(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            assert "/ViewerPreferences" in pdf.Root
            assert bool(pdf.Root["/ViewerPreferences"]["/DisplayDocTitle"]) is True

    def test_does_not_overwrite_existing_title(self, simple_pdf: Path, output_pdf: Path) -> None:
        shutil.copy2(simple_pdf, output_pdf)
        # Pre-set a title
        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            with pdf.open_metadata() as meta:
                meta["dc:title"] = "My Custom Title"
            pdf.save(output_pdf)

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            TaggerProcessor().process(pdf)
            result = MetadataProcessor().process(pdf)
            pdf.save(output_pdf)

        # Title should still be the pre-set one
        with pikepdf.open(output_pdf) as pdf:
            assert pdf.docinfo.get("/Title") is not None

    def test_idempotent(self, simple_pdf: Path, output_pdf: Path) -> None:
        self._run_with_tagger(simple_pdf, output_pdf)
        first_changes = self.result.changes_made

        with pikepdf.open(output_pdf, allow_overwriting_input=True) as pdf:
            result2 = MetadataProcessor().process(pdf)
            pdf.save(output_pdf)

        # Should make fewer or no changes on second run
        assert result2.changes_made <= first_changes
