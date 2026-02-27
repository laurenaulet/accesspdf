"""Remediation pipeline — orchestrates processors in sequence."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pikepdf

from accesspdf.models import ProcessorResult, RemediationResult
from accesspdf.processors.base import Processor

logger = logging.getLogger(__name__)

# Processors are registered here in execution order.
_PROCESSORS: list[type[Processor]] = []
_all_registered: bool = False


def register_processor(cls: type[Processor]) -> type[Processor]:
    """Class decorator that adds a processor to the pipeline registry."""
    if cls not in _PROCESSORS:
        _PROCESSORS.append(cls)
    return cls


def run_pipeline(
    input_path: Path,
    output_path: Path,
    *,
    alt_text_sidecar: Path | None = None,
) -> RemediationResult:
    """Run the full remediation pipeline on a PDF.

    1. Copies input to output (never modifies the original).
    2. Runs each registered processor in order.
    3. Optionally injects approved alt text from a sidecar file.
    """
    # Ensure all processors are registered (lazy to avoid circular imports)
    global _all_registered
    if not _all_registered:
        from accesspdf.processors import _register_all
        _register_all()
        _all_registered = True

    result = RemediationResult(source_path=input_path, output_path=output_path)

    # Step 1: Copy to output so we only ever mutate the copy
    shutil.copy2(input_path, output_path)

    # Step 2: Run processors
    with pikepdf.open(output_path, allow_overwriting_input=True) as pdf:
        for processor_cls in _PROCESSORS:
            proc = processor_cls()  # type: ignore[call-arg]
            proc_result = _run_single_processor(proc, pdf)
            result.processor_results.append(proc_result)

        pdf.save(output_path)

    # Step 3: Create/update sidecar with detected images
    _create_sidecar(output_path)

    # Step 4: Alt text injection (if sidecar provided)
    if alt_text_sidecar is not None:
        _inject_alt_text(output_path, alt_text_sidecar, result)

    return result


def _run_single_processor(proc: Processor, pdf: pikepdf.Pdf) -> ProcessorResult:
    """Run a single processor, catching unexpected exceptions."""
    try:
        return proc.process(pdf)
    except Exception as exc:
        logger.error("Processor %s failed: %s", proc.name, exc, exc_info=True)
        return ProcessorResult(
            processor_name=proc.name,
            success=False,
            error=str(exc),
        )


def _create_sidecar(output_path: Path) -> None:
    """Analyze the output PDF for images and create/update the sidecar file."""
    try:
        from accesspdf.analyzer import PDFAnalyzer
        from accesspdf.alttext.sidecar import SidecarManager

        analysis = PDFAnalyzer().analyze(output_path)
        if not analysis.images:
            return

        sidecar, sidecar_path = SidecarManager.load_or_create(output_path)
        for image in analysis.images:
            sidecar.upsert(image)

        SidecarManager.save(sidecar, sidecar_path)
        logger.info("Sidecar written to %s (%d images)", sidecar_path, len(sidecar.images))
    except Exception:
        logger.warning("Sidecar creation failed", exc_info=True)


def _inject_alt_text(
    output_path: Path, sidecar_path: Path, result: RemediationResult
) -> None:
    """Inject approved alt text from sidecar into the output PDF."""
    try:
        from accesspdf.alttext.injector import inject_alt_text
        from accesspdf.alttext.sidecar import SidecarManager

        sidecar = SidecarManager.load(sidecar_path)
        count = inject_alt_text(output_path, sidecar)
        result.processor_results.append(
            ProcessorResult(
                processor_name="AltTextInjector",
                success=True,
                changes_made=count,
            )
        )
    except Exception as exc:
        logger.error("Alt text injection failed: %s", exc, exc_info=True)
        result.processor_results.append(
            ProcessorResult(
                processor_name="AltTextInjector",
                success=False,
                error=str(exc),
            )
        )
