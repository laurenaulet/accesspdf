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

    # Count tags by type for summary
    link_count = sum(1 for t in result.tags if t.tag_type == "Link")
    table_count = sum(1 for t in result.tags if t.tag_type == "Table")
    contrast_issues = [i for i in result.issues if i.rule.startswith("contrast-")]

    table = Table(title=f"Accessibility Report: {pdf.name}")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Pages", str(result.page_count))
    table.add_row("Tagged", "Yes" if result.is_tagged else "[red]No[/red]")
    table.add_row("Language set", "Yes" if result.has_lang else "[red]No[/red]")
    table.add_row("Title", result.title or "[red]Not set[/red]")
    table.add_row("Images found", str(len(result.images)))
    table.add_row("Links found", str(link_count))
    table.add_row("Tables found", str(table_count))
    table.add_row(
        "Contrast",
        "[green]OK[/green]" if not contrast_issues else f"[yellow]{len(contrast_issues)} issue(s)[/yellow]",
    )
    table.add_row("Errors", str(result.error_count))
    table.add_row("Warnings", str(result.warning_count))

    console.print(table)

    if result.issues:
        console.print()
        severity_icon = {
            "error": "[red]X[/red]",
            "warning": "[yellow]![/yellow]",
            "info": "[blue]i[/blue]",
        }
        for issue in result.issues:
            icon = severity_icon.get(issue.severity.value, " ")
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
def review(
    pdf: Path = typer.Argument(..., help="Path to a PDF (or its output) to review alt text."),
) -> None:
    """Open TUI to review and approve alt text for images."""
    if not pdf.is_file():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    from accesspdf.alttext.sidecar import SidecarManager

    sidecar, sidecar_path = SidecarManager.load_or_create(pdf)

    if not sidecar.images:
        # Try to populate sidecar from the PDF's images
        from accesspdf.analyzer import PDFAnalyzer

        analysis = PDFAnalyzer().analyze(pdf)
        if not analysis.images:
            console.print("[dim]No images found in this PDF. Nothing to review.[/dim]")
            raise typer.Exit()

        for image in analysis.images:
            sidecar.upsert(image)
        SidecarManager.save(sidecar, sidecar_path)
        console.print(f"[dim]Created sidecar with {len(sidecar.images)} image(s): {sidecar_path.name}[/dim]")

    console.print(f"[dim]Reviewing {len(sidecar.images)} image(s) in {pdf.name}[/dim]")

    from accesspdf.review.app import ReviewApp

    app_instance = ReviewApp(pdf_path=pdf, sidecar=sidecar, sidecar_path=sidecar_path)
    app_instance.run()

    console.print(f"[green]OK[/green] Sidecar saved to {sidecar_path.name}")


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="Directory containing PDF files to fix."),
    output_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--output-dir", "-o", help="Output directory. Defaults to <dir>/accessible/.",
    ),
    alt_text_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--alt-text-dir", help="Directory with .alttext.yaml sidecar files to inject.",
    ),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Search subdirectories."),
) -> None:
    """Fix all PDFs in a directory at once."""
    if not directory.is_dir():
        console.print(f"[red]Not a directory:[/red] {directory}")
        raise typer.Exit(code=1)

    # Collect PDF files
    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_files = sorted(directory.glob(pattern))
    pdf_files = [p for p in pdf_files if p.is_file()]

    if not pdf_files:
        console.print(f"[dim]No PDF files found in {directory}[/dim]")
        raise typer.Exit()

    # Determine output directory
    if output_dir is None:
        output_dir = directory / "accessible"
    output_dir.mkdir(parents=True, exist_ok=True)

    from accesspdf.models import BatchResult
    from accesspdf.pipeline import run_pipeline
    from rich.progress import Progress

    batch_result = BatchResult()

    console.print(f"[dim]Processing {len(pdf_files)} PDF(s) from {directory}[/dim]")
    console.print(f"[dim]Output to: {output_dir}[/dim]")

    with Progress(console=console) as progress:
        task = progress.add_task("Fixing PDFs...", total=len(pdf_files))

        for pdf_path in pdf_files:
            out_path = output_dir / f"{pdf_path.stem}_accessible.pdf"

            # Look for matching sidecar if alt_text_dir provided
            sidecar_path = None
            if alt_text_dir:
                candidate = alt_text_dir / f"{pdf_path.stem}.alttext.yaml"
                if candidate.is_file():
                    sidecar_path = candidate

            try:
                result = run_pipeline(pdf_path, out_path, alt_text_sidecar=sidecar_path)
                batch_result.results.append(result)
            except Exception as exc:
                batch_result.failed.append((pdf_path, str(exc)))

            progress.advance(task)

    # Summary table
    table = Table(title="Batch Results")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total files", str(batch_result.total_files))
    table.add_row("Succeeded", f"[green]{batch_result.succeeded_count}[/green]")
    if batch_result.failed_count > 0:
        table.add_row("Failed", f"[red]{batch_result.failed_count}[/red]")
    else:
        table.add_row("Failed", "0")
    table.add_row("Total changes", str(batch_result.total_changes))
    console.print(table)

    if batch_result.failed:
        console.print()
        for path, error in batch_result.failed:
            console.print(f"  [red]X[/red] {path.name}: {error}")


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", "-p", help="Port to serve on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
) -> None:
    """Start web UI for browser-based alt text review."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Web UI requires extra dependencies.[/red]\n"
            "Install them with: [bold]pip install accesspdf\\[web\\][/bold]"
        )
        raise typer.Exit(code=1)

    from accesspdf.web.app import create_app

    console.print(f"[dim]Starting web UI at http://{host}:{port}[/dim]")

    import webbrowser
    webbrowser.open(f"http://{host}:{port}")

    web_app = create_app()
    uvicorn.run(web_app, host=host, port=port, log_level="warning")


@app.command(name="generate-alt-text")
def generate_alt_text(
    pdf: Path = typer.Argument(..., help="Path to a fixed PDF (with sidecar) to generate alt text for."),
    provider: str = typer.Option("ollama", "--provider", "-p", help="AI provider to use."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model override."),  # noqa: UP007
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key (or set env var)."),  # noqa: UP007
) -> None:
    """Generate AI alt text drafts for images in a PDF."""
    import asyncio

    if not pdf.is_file():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    from accesspdf.alttext.sidecar import SidecarManager

    sidecar, sidecar_path = SidecarManager.load_or_create(pdf)

    if not sidecar.images:
        # Try to populate sidecar from the PDF's images
        from accesspdf.analyzer import PDFAnalyzer

        analysis = PDFAnalyzer().analyze(pdf)
        if not analysis.images:
            console.print("[dim]No images found in this PDF.[/dim]")
            raise typer.Exit()

        for image in analysis.images:
            sidecar.upsert(image)
        SidecarManager.save(sidecar, sidecar_path)

    # Filter to images that need AI drafts
    from accesspdf.models import AltTextStatus

    pending = [e for e in sidecar.images if not e.ai_draft and e.status == AltTextStatus.NEEDS_REVIEW]
    if not pending:
        console.print("[dim]All images already have AI drafts or are approved.[/dim]")
        raise typer.Exit()

    # Create provider
    from accesspdf.providers import get_provider

    kwargs: dict = {}
    if model:
        kwargs["model"] = model
    try:
        prov = get_provider(provider, api_key=api_key, **kwargs)
    except (ValueError, ImportError) as exc:
        console.print(f"[red]Provider error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[dim]Provider:[/dim] {prov.name}")
    console.print(f"[dim]Generating drafts for {len(pending)} image(s)...[/dim]")

    # Generate
    from accesspdf.alttext.extract import extract_image
    from accesspdf.providers.base import ImageContext
    from rich.progress import Progress

    async def _generate_all() -> int:
        count = 0
        with Progress(console=console) as progress:
            task = progress.add_task("Generating...", total=len(pending))
            for entry in pending:
                img = extract_image(pdf, entry.hash)
                if img is None:
                    progress.advance(task)
                    continue

                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                context = ImageContext(
                    image_bytes=buf.getvalue(),
                    page=entry.page,
                    caption=entry.caption,
                    document_title=sidecar.document,
                )

                result = await prov.generate(context)
                if result.alt_text:
                    entry.ai_draft = result.alt_text
                    count += 1
                elif result.error:
                    console.print(f"  [yellow]![/yellow] {entry.id}: {result.error}")

                progress.advance(task)
        return count

    generated = asyncio.run(_generate_all())
    SidecarManager.save(sidecar, sidecar_path)

    console.print(f"[green]OK[/green] Generated {generated} draft(s). Sidecar saved to {sidecar_path.name}")
    console.print("[dim]Run 'accesspdf review' to approve or edit the drafts.[/dim]")


@app.command()
def providers() -> None:
    """Show available AI providers and their status."""
    from accesspdf.providers import list_available

    results = list_available()

    table = Table(title="AI Providers")
    table.add_column("Provider", style="bold")
    table.add_column("Available")
    table.add_column("Notes")

    notes_map = {
        "ollama": "Local — no API key needed",
        "anthropic": "Needs ANTHROPIC_API_KEY env var",
        "openai": "Needs OPENAI_API_KEY env var",
        "gemini": "Needs GOOGLE_API_KEY env var",
        "noop": "No-op — flags for manual review",
    }

    for name, available in results:
        status = "[green]Yes[/green]" if available else "[red]No[/red]"
        table.add_row(name, status, notes_map.get(name, ""))

    console.print(table)
