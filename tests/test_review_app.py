"""Tests for the ReviewApp TUI (headless via Textual test harness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from accesspdf.alttext.sidecar import AltTextEntry, SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus
from accesspdf.pipeline import run_pipeline
from accesspdf.review.app import ReviewApp


def _make_review_app(pdf_path: Path, tmp_path: Path) -> ReviewApp:
    """Create a ReviewApp with a real PDF and sidecar."""
    out = tmp_path / "out.pdf"
    run_pipeline(pdf_path, out)

    sidecar_path = out.with_suffix(".alttext.yaml")
    if sidecar_path.exists():
        sidecar = SidecarManager.load(sidecar_path)
    else:
        sidecar = SidecarFile(document=out.name)

    return ReviewApp(pdf_path=out, sidecar=sidecar, sidecar_path=sidecar_path)


@pytest.mark.asyncio
async def test_app_starts_and_shows_images(images_pdf: Path, tmp_path: Path) -> None:
    app = _make_review_app(images_pdf, tmp_path)
    async with app.run_test() as pilot:
        assert len(app.entries) == 3
        assert app.current_index == 0
        assert app.current_entry is not None


@pytest.mark.asyncio
async def test_navigation(images_pdf: Path, tmp_path: Path) -> None:
    app = _make_review_app(images_pdf, tmp_path)
    async with app.run_test() as pilot:
        assert app.current_index == 0

        await pilot.press("n")
        assert app.current_index == 1

        await pilot.press("n")
        assert app.current_index == 2

        # Can't go past last
        await pilot.press("n")
        assert app.current_index == 2

        await pilot.press("p")
        assert app.current_index == 1

        await pilot.press("p")
        assert app.current_index == 0

        # Can't go before first
        await pilot.press("p")
        assert app.current_index == 0


@pytest.mark.asyncio
async def test_approve_action(images_pdf: Path, tmp_path: Path) -> None:
    app = _make_review_app(images_pdf, tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("a")
        assert app.entries[0].status == AltTextStatus.APPROVED


@pytest.mark.asyncio
async def test_decorative_action(images_pdf: Path, tmp_path: Path) -> None:
    app = _make_review_app(images_pdf, tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("d")
        assert app.entries[0].status == AltTextStatus.DECORATIVE
        assert app.entries[0].alt_text == ""


@pytest.mark.asyncio
async def test_save_writes_sidecar(images_pdf: Path, tmp_path: Path) -> None:
    app = _make_review_app(images_pdf, tmp_path)
    async with app.run_test() as pilot:
        # Set alt text via the widget
        from accesspdf.review.widgets import AltTextEditor
        editor = app.query_one("#alt-editor", AltTextEditor)
        editor.value = "Test description"

        # Approve and save
        await pilot.press("a")
        await pilot.press("ctrl+s")

        # Reload from disk
        reloaded = SidecarManager.load(app.sidecar_path)
        assert reloaded.images[0].status == AltTextStatus.APPROVED


@pytest.mark.asyncio
async def test_no_images_graceful(simple_pdf: Path, tmp_path: Path) -> None:
    """App should handle PDFs with no images gracefully."""
    app = _make_review_app(simple_pdf, tmp_path)
    async with app.run_test() as pilot:
        assert len(app.entries) == 0
        assert app.current_entry is None
        # Navigation shouldn't crash
        await pilot.press("n")
        await pilot.press("p")
        await pilot.press("a")
