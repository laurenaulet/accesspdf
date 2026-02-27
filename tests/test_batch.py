"""Tests for the batch command."""

from __future__ import annotations

import shutil
from pathlib import Path

from accesspdf.models import BatchResult
from accesspdf.pipeline import run_pipeline


class TestBatchResult:
    def test_empty_batch(self) -> None:
        result = BatchResult()
        assert result.total_files == 0
        assert result.succeeded_count == 0
        assert result.failed_count == 0
        assert result.total_changes == 0

    def test_counts(self, simple_pdf: Path, output_pdf: Path) -> None:
        r = run_pipeline(simple_pdf, output_pdf)
        batch = BatchResult(results=[r])
        assert batch.total_files == 1
        assert batch.succeeded_count == 1
        assert batch.failed_count == 0
        assert batch.total_changes > 0

    def test_failed_tracking(self, tmp_path: Path) -> None:
        batch = BatchResult(failed=[(tmp_path / "bad.pdf", "Some error")])
        assert batch.total_files == 1
        assert batch.failed_count == 1
        assert batch.succeeded_count == 0


class TestBatchProcessing:
    def test_processes_directory(self, corpus_dir: Path, tmp_path: Path) -> None:
        """Batch processes all PDFs in the corpus directory."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        pdf_files = sorted(corpus_dir.glob("*.pdf"))
        batch = BatchResult()

        for pdf_path in pdf_files:
            out_path = out_dir / f"{pdf_path.stem}_accessible.pdf"
            try:
                result = run_pipeline(pdf_path, out_path)
                batch.results.append(result)
            except Exception as exc:
                batch.failed.append((pdf_path, str(exc)))

        assert batch.succeeded_count == len(pdf_files)
        assert batch.failed_count == 0
        assert batch.total_changes > 0

        # Verify output files exist
        output_files = list(out_dir.glob("*.pdf"))
        assert len(output_files) == len(pdf_files)

    def test_failure_nonfatal(self, corpus_dir: Path, tmp_path: Path) -> None:
        """A bad PDF doesn't stop processing of others."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        # Create a bad "PDF" file
        bad_pdf = tmp_path / "bad.pdf"
        bad_pdf.write_text("not a real pdf")

        files = [bad_pdf, corpus_dir / "simple.pdf"]
        batch = BatchResult()

        for pdf_path in files:
            out_path = out_dir / f"{pdf_path.stem}_accessible.pdf"
            try:
                result = run_pipeline(pdf_path, out_path)
                batch.results.append(result)
            except Exception as exc:
                batch.failed.append((pdf_path, str(exc)))

        assert batch.succeeded_count == 1  # simple.pdf succeeded
        assert batch.failed_count == 1     # bad.pdf failed

    def test_skips_non_pdf(self, tmp_path: Path) -> None:
        """Non-PDF files in directory are skipped by glob pattern."""
        test_dir = tmp_path / "mixed"
        test_dir.mkdir()

        # Create non-PDF file
        (test_dir / "readme.txt").write_text("not a pdf")
        (test_dir / "data.csv").write_text("a,b,c")

        pdf_files = list(test_dir.glob("*.pdf"))
        assert len(pdf_files) == 0
