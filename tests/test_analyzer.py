"""Tests for the PDF analyzer, focusing on scanned PDF detection."""

from __future__ import annotations

from pathlib import Path

from accesspdf.analyzer import PDFAnalyzer


class TestScannedDetection:
    def test_scanned_pdf_detected(self, scanned_pdf: Path) -> None:
        """A scanned (image-only) PDF should be flagged as is_scanned."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(scanned_pdf)
        assert result.is_scanned is True

    def test_scanned_pdf_has_warning_issue(self, scanned_pdf: Path) -> None:
        """A scanned PDF should have a 'scanned-pdf' warning issue."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(scanned_pdf)
        scanned_issues = [i for i in result.issues if i.rule == "scanned-pdf"]
        assert len(scanned_issues) == 1
        assert scanned_issues[0].severity.value == "warning"
        assert "OCR" in scanned_issues[0].message

    def test_normal_pdf_not_scanned(self, simple_pdf: Path) -> None:
        """A normal text PDF should NOT be flagged as scanned."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(simple_pdf)
        assert result.is_scanned is False
        scanned_issues = [i for i in result.issues if i.rule == "scanned-pdf"]
        assert len(scanned_issues) == 0

    def test_images_pdf_not_scanned(self, images_pdf: Path) -> None:
        """A PDF with images AND text should NOT be flagged as scanned."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(images_pdf)
        assert result.is_scanned is False
