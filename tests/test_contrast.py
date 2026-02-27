"""Tests for contrast utilities and analyzer contrast/link/table checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from accesspdf.utils.contrast import (
    contrast_ratio,
    parse_pdf_color,
    passes_aa,
    relative_luminance,
)


class TestRelativeLuminance:
    def test_black(self) -> None:
        assert relative_luminance(0, 0, 0) == pytest.approx(0.0, abs=1e-6)

    def test_white(self) -> None:
        assert relative_luminance(255, 255, 255) == pytest.approx(1.0, abs=1e-4)

    def test_mid_gray(self) -> None:
        lum = relative_luminance(128, 128, 128)
        assert 0.2 < lum < 0.25  # ~0.2158

    def test_pure_red(self) -> None:
        lum = relative_luminance(255, 0, 0)
        assert 0.20 < lum < 0.22  # ~0.2126


class TestContrastRatio:
    def test_black_on_white(self) -> None:
        ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
        assert ratio == pytest.approx(21.0, abs=0.1)

    def test_white_on_white(self) -> None:
        ratio = contrast_ratio((255, 255, 255), (255, 255, 255))
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_symmetric(self) -> None:
        r1 = contrast_ratio((100, 50, 200), (200, 100, 50))
        r2 = contrast_ratio((200, 100, 50), (100, 50, 200))
        assert r1 == pytest.approx(r2, abs=0.01)

    def test_light_gray_on_white(self) -> None:
        # Light gray (217, 217, 217) on white should fail AA
        ratio = contrast_ratio((217, 217, 217), (255, 255, 255))
        assert ratio < 4.5


class TestPassesAA:
    def test_passes_normal(self) -> None:
        assert passes_aa(4.5) is True

    def test_fails_normal(self) -> None:
        assert passes_aa(4.4) is False

    def test_passes_large_text(self) -> None:
        assert passes_aa(3.0, large_text=True) is True

    def test_fails_large_text(self) -> None:
        assert passes_aa(2.9, large_text=True) is False


class TestParsePdfColor:
    def test_rgb(self) -> None:
        assert parse_pdf_color([1.0, 0.0, 0.0], "rgb") == (255, 0, 0)

    def test_gray(self) -> None:
        assert parse_pdf_color([0.5], "gray") == (128, 128, 128)

    def test_cmyk_black(self) -> None:
        # CMYK (0, 0, 0, 1) = black
        assert parse_pdf_color([0, 0, 0, 1.0], "cmyk") == (0, 0, 0)

    def test_cmyk_white(self) -> None:
        # CMYK (0, 0, 0, 0) = white
        assert parse_pdf_color([0, 0, 0, 0], "cmyk") == (255, 255, 255)

    def test_unknown_space_returns_black(self) -> None:
        assert parse_pdf_color([0.5, 0.5], "lab") == (0, 0, 0)


class TestAnalyzerContrast:
    def test_low_contrast_detected(self, low_contrast_pdf: Path) -> None:
        from accesspdf.analyzer import PDFAnalyzer

        result = PDFAnalyzer().analyze(low_contrast_pdf)
        contrast_rules = [i.rule for i in result.issues if i.rule.startswith("contrast-")]
        assert len(contrast_rules) > 0, "Should detect contrast issues"

    def test_normal_contrast_no_issue(self, simple_pdf: Path) -> None:
        from accesspdf.analyzer import PDFAnalyzer

        result = PDFAnalyzer().analyze(simple_pdf)
        contrast_rules = [i.rule for i in result.issues if i.rule.startswith("contrast-")]
        # simple_pdf uses default black text; should not flag
        assert len(contrast_rules) == 0


class TestAnalyzerLinks:
    def test_no_link_issues_in_simple(self, simple_pdf: Path) -> None:
        from accesspdf.analyzer import PDFAnalyzer

        result = PDFAnalyzer().analyze(simple_pdf)
        link_rules = [i.rule for i in result.issues if i.rule.startswith("link-")]
        assert len(link_rules) == 0


class TestAnalyzerTables:
    def test_no_table_issues_in_simple(self, simple_pdf: Path) -> None:
        from accesspdf.analyzer import PDFAnalyzer

        result = PDFAnalyzer().analyze(simple_pdf)
        table_rules = [i.rule for i in result.issues if i.rule.startswith("table-")]
        assert len(table_rules) == 0
