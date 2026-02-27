"""End-to-end integration tests for the full remediation pipeline."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import patch

import pikepdf
import pytest

from accesspdf.analyzer import PDFAnalyzer
from accesspdf.pipeline import run_pipeline
from tests.utils.validate import validate_tag_tree


class TestPipelineIntegration:
    def test_all_processors_run(self, simple_pdf: Path, output_pdf: Path) -> None:
        result = run_pipeline(simple_pdf, output_pdf)
        names = [r.processor_name for r in result.processor_results]
        assert "TagStructure" in names
        assert "Metadata" in names
        assert "ReadingOrder" in names
        assert "Headings" in names
        assert "Tables" in names
        assert "Links" in names
        assert "Bookmarks" in names
        assert len(result.processor_results) == 7

    def test_output_differs_from_input(self, simple_pdf: Path, output_pdf: Path) -> None:
        run_pipeline(simple_pdf, output_pdf)
        assert output_pdf.exists()
        # Output should differ from input (structural changes made)
        src_hash = hashlib.md5(simple_pdf.read_bytes()).hexdigest()
        out_hash = hashlib.md5(output_pdf.read_bytes()).hexdigest()
        assert src_hash != out_hash

    def test_original_unmodified(self, simple_pdf: Path, output_pdf: Path) -> None:
        src_hash_before = hashlib.md5(simple_pdf.read_bytes()).hexdigest()
        run_pipeline(simple_pdf, output_pdf)
        src_hash_after = hashlib.md5(simple_pdf.read_bytes()).hexdigest()
        assert src_hash_before == src_hash_after

    def test_output_is_tagged(self, simple_pdf: Path, output_pdf: Path) -> None:
        run_pipeline(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            assert "/StructTreeRoot" in pdf.Root
            assert "/MarkInfo" in pdf.Root
            assert bool(pdf.Root["/MarkInfo"]["/Marked"]) is True

    def test_output_has_language(self, simple_pdf: Path, output_pdf: Path) -> None:
        run_pipeline(simple_pdf, output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            assert "/Lang" in pdf.Root

    def test_tag_tree_valid(self, simple_pdf: Path, output_pdf: Path) -> None:
        run_pipeline(simple_pdf, output_pdf)
        validation = validate_tag_tree(output_pdf)
        assert validation.valid is True
        assert len(validation.errors) == 0

    def test_fix_then_check_fewer_issues(self, simple_pdf: Path, output_pdf: Path) -> None:
        analyzer = PDFAnalyzer()

        before = analyzer.analyze(simple_pdf)
        run_pipeline(simple_pdf, output_pdf)
        after = analyzer.analyze(output_pdf)

        assert after.error_count <= before.error_count
        assert after.is_tagged is True
        assert after.has_lang is True

    def test_headings_pdf_full_pipeline(self, headings_pdf: Path, output_pdf: Path) -> None:
        result = run_pipeline(headings_pdf, output_pdf)
        assert result.all_succeeded
        assert result.total_changes > 0

        validation = validate_tag_tree(output_pdf)
        assert validation.valid is True

    def test_processor_failure_nonfatal(self, simple_pdf: Path, output_pdf: Path) -> None:
        """If one processor raises, others should still run."""
        from accesspdf.processors.headings import HeadingsProcessor

        original_process = HeadingsProcessor._process_headings

        def broken_process(self_inner, pdf):
            raise RuntimeError("Simulated failure")

        with patch.object(HeadingsProcessor, "_process_headings", broken_process):
            result = run_pipeline(simple_pdf, output_pdf)

        names = [r.processor_name for r in result.processor_results]
        assert "Headings" in names  # ran (and failed)
        assert "Bookmarks" in names  # still ran after failure

        headings_result = next(r for r in result.processor_results if r.processor_name == "Headings")
        assert headings_result.success is False

        # Other processors should have succeeded
        tagger_result = next(r for r in result.processor_results if r.processor_name == "TagStructure")
        assert tagger_result.success is True
