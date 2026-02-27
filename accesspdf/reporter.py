"""Report generation — JSON, Markdown, and HTML output."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from accesspdf.models import AnalysisResult, RemediationResult


def write_json_report(result: AnalysisResult, output: Path) -> None:
    """Write an analysis result as a JSON report."""
    data = asdict(result)
    # Convert Path to string for JSON serialization
    data["source_path"] = str(result.source_path)
    output.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_markdown_report(result: AnalysisResult, output: Path) -> None:
    """Write an analysis result as a Markdown report."""
    lines: list[str] = [
        f"# Accessibility Report: {result.source_path.name}",
        "",
        f"- **Pages:** {result.page_count}",
        f"- **Tagged:** {'Yes' if result.is_tagged else 'No'}",
        f"- **Language:** {result.detected_lang or 'Not set'}",
        f"- **Title:** {result.title or 'Not set'}",
        f"- **Images:** {len(result.images)}",
        "",
        f"## Issues ({result.error_count} errors, {result.warning_count} warnings)",
        "",
    ]

    for issue in result.issues:
        marker = "ERROR" if issue.severity.value == "error" else "WARN"
        lines.append(f"- **[{marker}]** `{issue.rule}`: {issue.message}")

    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def format_remediation_summary(result: RemediationResult) -> str:
    """Return a human-readable summary of a remediation run."""
    lines = [
        f"Remediation: {result.source_path.name} -> {result.output_path.name}",
        f"Total changes: {result.total_changes}",
    ]
    for pr in result.processor_results:
        status = "OK" if pr.success else "FAILED"
        lines.append(f"  [{status}] {pr.processor_name}: {pr.changes_made} change(s)")
        if pr.error:
            lines.append(f"         Error: {pr.error}")
    return "\n".join(lines)
