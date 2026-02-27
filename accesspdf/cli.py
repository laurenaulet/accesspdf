"""CLI entry point — all commands defined here."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from accesspdf import __version__

app = typer.Typer(
    name="accesspdf",
    help="PDF accessibility remediation tool.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"accesspdf {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(  # noqa: UP007
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """AccessPDF — PDF accessibility remediation."""


@app.command()
def check(
    pdf: Path = typer.Argument(..., help="Path to the PDF file to analyze."),
) -> None:
    """Analyze a PDF for accessibility issues (no modification)."""
    from accesspdf.analyzer import PDFAnalyzer

    if not pdf.is_file():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    analyzer = PDFAnalyzer()
    result = analyzer.analyze(pdf)

    table = Table(title=f"Accessibility Report: {pdf.name}")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Pages", str(result.page_count))
    table.add_row("Tagged", "Yes" if result.is_tagged else "[red]No[/red]")
    table.add_row("Language set", "Yes" if result.has_lang else "[red]No[/red]")
    table.add_row("Title", result.title or "[red]Not set[/red]")
    table.add_row("Images found", str(len(result.images)))
    table.add_row("Errors", str(result.error_count))
    table.add_row("Warnings", str(result.warning_count))

    console.print(table)

    if result.issues:
        console.print()
        for issue in result.issues:
            icon = "[red]X[/red]" if issue.severity.value == "error" else "[yellow]![/yellow]"
            console.print(f"  {icon} [{issue.rule}] {issue.message}")


@app.command()
def fix(
    pdf: Path = typer.Argument(..., help="Path to the PDF file to fix."),
    output: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--output", "-o", help="Output path. Defaults to <name>_accessible.pdf.",
    ),
    alt_text: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--alt-text", help="Sidecar YAML with approved alt text to inject.",
    ),
) -> None:
    """Apply structural fixes and optionally inject alt text."""
    if not pdf.is_file():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    # Determine output path
    if output is None:
        output = pdf.with_stem(pdf.stem + "_accessible")

    if output.resolve() == pdf.resolve():
        console.print("[red]Output path must differ from input — never modify the original.[/red]")
        raise typer.Exit(code=1)

    console.print(f"[dim]Fixing:[/dim] {pdf}")
    console.print(f"[dim]Output:[/dim] {output}")

    from accesspdf.pipeline import run_pipeline

    result = run_pipeline(pdf, output, alt_text_sidecar=alt_text)

    if result.all_succeeded:
        console.print(f"[green]OK[/green] Done -- {result.total_changes} change(s) applied.")
    else:
        console.print("[yellow]Completed with warnings.[/yellow]")
        for w in result.warnings:
            console.print(f"  [yellow]![/yellow] {w}")


@app.command()
def providers() -> None:
    """Show available AI providers and their status."""
    console.print("[dim]Provider availability check not yet implemented.[/dim]")
