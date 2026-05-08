"""Tests for CLI commands, especially the check command with --verbose flag."""

from __future__ import annotations

from pathlib import Path
import json

import pytest
from typer.testing import CliRunner

from accesspdf.analyzer import PDFAnalyzer
from accesspdf.cli import app
from accesspdf.models import AccessibilityIssue, Severity


runner = CliRunner()


class TestCheckCommand:
    def test_check_file_not_found(self) -> None:
        """Check command should fail gracefully if file doesn't exist."""
        result = runner.invoke(app, ["check", "nonexistent.pdf"])
        assert result.exit_code == 1
        assert "File not found" in result.stdout

    def test_check_without_verbose(self, low_contrast_pdf: Path) -> None:
        """Check command without --verbose should show summary format."""
        result = runner.invoke(app, ["check", str(low_contrast_pdf)])
        assert result.exit_code == 0
        # Should show page count but NOT individual pages
        assert "on 1 page(s)" in result.stdout
        assert " - Pages:" not in result.stdout

    def test_check_with_verbose_flag(self, low_contrast_pdf: Path) -> None:
        """Check command with --verbose should show affected pages."""
        result = runner.invoke(app, ["check", str(low_contrast_pdf), "--verbose"])
        assert result.exit_code == 0
        # Should show page count AND individual pages
        assert "on 1 page(s)" in result.stdout
        assert " - Pages: 1" in result.stdout

    def test_check_with_verbose_tables(self, tables_pdf: Path) -> None:
        """Check command with --verbose should show affected pages for tables PDF."""
        result = runner.invoke(app, ["check", str(tables_pdf), "--verbose"])
        assert result.exit_code == 0
        # Should show affected pages
        assert " - Pages:" in result.stdout

    def test_check_with_json_flag(self, low_contrast_pdf: Path) -> None:
        """Check command with --json should output JSON with page arrays."""
        result = runner.invoke(app, ["check", str(low_contrast_pdf), "--json"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["source_path"].endswith("low_contrast.pdf")
        assert data["page_count"] == 1
        assert isinstance(data["issues"], list)

        contrast_issue = next(i for i in data["issues"] if i["rule"].startswith("contrast-"))
        assert contrast_issue["affected_pages"] == [1]


class TestAnalyzerAffectedPages:
    """Test that the analyzer populates affected_pages correctly."""

    def test_contrast_issues_have_affected_pages(self, low_contrast_pdf: Path) -> None:
        """Contrast issues should populate affected_pages."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(low_contrast_pdf)
        
        contrast_issues = [i for i in result.issues if i.rule.startswith("contrast-")]
        assert len(contrast_issues) > 0
        
        for issue in contrast_issues:
            assert issue.affected_pages is not None
            assert isinstance(issue.affected_pages, list)
            assert len(issue.affected_pages) > 0
            # Pages should be positive integers
            for page in issue.affected_pages:
                assert isinstance(page, int)
                assert page > 0

    def test_image_alt_text_issues_have_affected_pages(self, simple_pdf: Path) -> None:
        """Image alt text issues should populate affected_pages."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(simple_pdf)
        
        image_issues = [i for i in result.issues if i.rule == "image-alt-text"]
        if image_issues:
            for issue in image_issues:
                assert issue.affected_pages is not None
                assert isinstance(issue.affected_pages, list)
                assert len(issue.affected_pages) > 0

    def test_link_issues_have_affected_pages(self, links_pdf: Path) -> None:
        """Link issues should populate affected_pages."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(links_pdf)
        
        link_issues = [i for i in result.issues if "link" in i.rule]
        if link_issues:
            for issue in link_issues:
                assert issue.affected_pages is not None
                assert isinstance(issue.affected_pages, list)

    def test_affected_pages_are_sorted(self, low_contrast_pdf: Path) -> None:
        """Affected pages should be sorted in ascending order."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(low_contrast_pdf)
        
        for issue in result.issues:
            if issue.affected_pages:
                assert issue.affected_pages == sorted(issue.affected_pages)

    def test_affected_pages_no_duplicates(self, low_contrast_pdf: Path) -> None:
        """Affected pages should not contain duplicates."""
        analyzer = PDFAnalyzer()
        result = analyzer.analyze(low_contrast_pdf)
        
        for issue in result.issues:
            if issue.affected_pages:
                assert len(issue.affected_pages) == len(set(issue.affected_pages))


class TestIssueMessageFormatting:
    """Test the format_issue_message function."""

    def test_message_without_verbose_no_pages(self) -> None:
        """Issue message without verbose should not include pages."""
        from accesspdf.cli import _format_issue_message
        
        issue = AccessibilityIssue(
            rule="contrast-low",
            severity=Severity.ERROR,
            message="Low contrast on 5 page(s)",
            affected_pages=[1, 2, 3, 4, 5],
        )
        formatted = _format_issue_message(issue, verbose=False)
        assert "Pages:" not in formatted
        assert formatted == "Low contrast on 5 page(s)"

    def test_message_with_verbose_shows_pages(self) -> None:
        """Issue message with verbose should include affected pages."""
        from accesspdf.cli import _format_issue_message
        
        issue = AccessibilityIssue(
            rule="contrast-low",
            severity=Severity.ERROR,
            message="Low contrast on 5 page(s)",
            affected_pages=[1, 2, 3, 4, 5],
        )
        formatted = _format_issue_message(issue, verbose=True)
        assert "Pages:" in formatted
        assert "1, 2, 3, 4, 5" in formatted

    def test_message_with_verbose_no_affected_pages(self) -> None:
        """Message with verbose but no affected_pages should still work."""
        from accesspdf.cli import _format_issue_message
        
        issue = AccessibilityIssue(
            rule="document-title",
            severity=Severity.WARNING,
            message="Document title is not set",
            affected_pages=[],
        )
        formatted = _format_issue_message(issue, verbose=True)
        # Should just return the message without pages if list is empty
        assert formatted == "Document title is not set"
