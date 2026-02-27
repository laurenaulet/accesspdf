"""Tests for core data models."""

from __future__ import annotations

from pathlib import Path

from accesspdf.models import (
    AccessibilityIssue,
    AltTextStatus,
    AnalysisResult,
    ImageInfo,
    ProcessorResult,
    RemediationResult,
    Severity,
)


class TestImageInfo:
    def test_short_id(self) -> None:
        img = ImageInfo(image_hash="a3f8c2d901abcdef", page=1, width=100, height=200)
        assert img.short_id == "a3f8c2"

    def test_short_id_exact_six(self) -> None:
        img = ImageInfo(image_hash="123456", page=1, width=10, height=10)
        assert img.short_id == "123456"


class TestAnalysisResult:
    def test_error_and_warning_counts(self) -> None:
        result = AnalysisResult(
            source_path=Path("test.pdf"),
            issues=[
                AccessibilityIssue(rule="r1", severity=Severity.ERROR, message="e1"),
                AccessibilityIssue(rule="r2", severity=Severity.ERROR, message="e2"),
                AccessibilityIssue(rule="r3", severity=Severity.WARNING, message="w1"),
                AccessibilityIssue(rule="r4", severity=Severity.INFO, message="i1"),
            ],
        )
        assert result.error_count == 2
        assert result.warning_count == 1

    def test_empty_result(self) -> None:
        result = AnalysisResult(source_path=Path("empty.pdf"))
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.page_count == 0
        assert result.images == []


class TestRemediationResult:
    def test_total_changes(self) -> None:
        result = RemediationResult(
            source_path=Path("in.pdf"),
            output_path=Path("out.pdf"),
            processor_results=[
                ProcessorResult(processor_name="A", changes_made=3),
                ProcessorResult(processor_name="B", changes_made=5),
            ],
        )
        assert result.total_changes == 8

    def test_all_succeeded(self) -> None:
        result = RemediationResult(
            source_path=Path("in.pdf"),
            output_path=Path("out.pdf"),
            processor_results=[
                ProcessorResult(processor_name="A", success=True),
                ProcessorResult(processor_name="B", success=True),
            ],
        )
        assert result.all_succeeded is True

    def test_partial_failure(self) -> None:
        result = RemediationResult(
            source_path=Path("in.pdf"),
            output_path=Path("out.pdf"),
            processor_results=[
                ProcessorResult(processor_name="A", success=True),
                ProcessorResult(processor_name="B", success=False, error="boom"),
            ],
        )
        assert result.all_succeeded is False

    def test_warnings_aggregation(self) -> None:
        result = RemediationResult(
            source_path=Path("in.pdf"),
            output_path=Path("out.pdf"),
            processor_results=[
                ProcessorResult(processor_name="A", warnings=["w1"]),
                ProcessorResult(processor_name="B", warnings=["w2", "w3"]),
            ],
        )
        assert len(result.warnings) == 3
        assert "[A] w1" in result.warnings
        assert "[B] w2" in result.warnings


class TestAltTextStatus:
    def test_values(self) -> None:
        assert AltTextStatus.NEEDS_REVIEW.value == "needs_review"
        assert AltTextStatus.APPROVED.value == "approved"
        assert AltTextStatus.DECORATIVE.value == "decorative"
