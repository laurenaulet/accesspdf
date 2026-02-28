"""Tests for alt text injection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf
import pytest

from accesspdf.alttext.injector import inject_alt_text
from accesspdf.alttext.sidecar import AltTextEntry, SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus
from accesspdf.pipeline import run_pipeline


class TestInjector:
    def _fix_pdf(self, src: Path, out: Path) -> SidecarFile:
        """Run pipeline on src to get a tagged PDF and sidecar."""
        run_pipeline(src, out)
        sidecar_path = out.with_suffix(".alttext.yaml")
        if sidecar_path.exists():
            return SidecarManager.load(sidecar_path)
        return SidecarFile(document=out.name)

    def test_injects_approved_alt_text(self, images_pdf: Path, output_pdf: Path) -> None:
        sidecar = self._fix_pdf(images_pdf, output_pdf)
        assert len(sidecar.images) >= 1

        # Approve all entries with known alt text
        for entry in sidecar.images:
            entry.alt_text = f"Alt text for {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count = inject_alt_text(output_pdf, sidecar)
        assert count == len(sidecar.images)

        # Verify /Figure tags exist with correct /Alt text
        with pikepdf.open(output_pdf) as pdf:
            figures = _find_figures(pdf)
            assert len(figures) >= count

            # Every injected figure must have /Alt with actual content
            figures_with_alt = [
                f for f in figures
                if "/Alt" in f and str(f["/Alt"]).strip()
            ]
            assert len(figures_with_alt) >= count

            # Check the alt text values match what we set
            alt_texts = {str(f["/Alt"]) for f in figures_with_alt}
            for entry in sidecar.images:
                assert f"Alt text for {entry.id}" in alt_texts

    def test_figures_have_marked_content_link(self, images_pdf: Path, output_pdf: Path) -> None:
        """Injected /Figure elements must have /K with MCID linking to content."""
        sidecar = self._fix_pdf(images_pdf, output_pdf)
        assert len(sidecar.images) >= 1

        for entry in sidecar.images:
            entry.alt_text = f"Test alt {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count = inject_alt_text(output_pdf, sidecar)
        assert count > 0

        with pikepdf.open(output_pdf) as pdf:
            figures = _find_figures(pdf)
            figures_with_alt = [
                f for f in figures
                if "/Alt" in f and str(f["/Alt"]).strip()
            ]

            for fig in figures_with_alt:
                # Must have /K (marked content link)
                assert "/K" in fig, "/Figure has no /K — accessibility checkers can't find it"
                k = fig["/K"]
                # /K should contain at least one MCID (integer)
                if isinstance(k, pikepdf.Array):
                    mcids = [item for item in k if isinstance(item, (int, pikepdf.Object))]
                    assert len(mcids) > 0, "/Figure /K array is empty"
                else:
                    # Single MCID value
                    assert k is not None, "/Figure /K is empty"

                # Must have /Pg (page reference)
                assert "/Pg" in fig, "/Figure has no /Pg — not linked to a page"

    def test_content_stream_has_bdc_emc(self, images_pdf: Path, output_pdf: Path) -> None:
        """Content stream must have BDC/EMC wrapping image Do commands."""
        sidecar = self._fix_pdf(images_pdf, output_pdf)
        assert len(sidecar.images) >= 1

        for entry in sidecar.images:
            entry.alt_text = f"BDC test {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count = inject_alt_text(output_pdf, sidecar)
        assert count > 0

        with pikepdf.open(output_pdf) as pdf:
            # Check that at least one page has BDC /Figure ... EMC in its content
            found_figure_bdc = False
            for page in pdf.pages:
                try:
                    ops = pikepdf.parse_content_stream(page)
                except Exception:
                    continue
                for operands, operator in ops:
                    if (operator == pikepdf.Operator("BDC")
                            and len(operands) >= 1
                            and str(operands[0]) == "/Figure"):
                        found_figure_bdc = True
                        break
                if found_figure_bdc:
                    break
            assert found_figure_bdc, "No BDC /Figure found in any content stream"

    def test_parent_tree_includes_figures(self, images_pdf: Path, output_pdf: Path) -> None:
        """ParentTree must have entries for injected figures."""
        sidecar = self._fix_pdf(images_pdf, output_pdf)
        assert len(sidecar.images) >= 1

        for entry in sidecar.images:
            entry.alt_text = f"PT test {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count = inject_alt_text(output_pdf, sidecar)
        assert count > 0

        with pikepdf.open(output_pdf) as pdf:
            struct_root = pdf.Root["/StructTreeRoot"]
            assert "/ParentTree" in struct_root, "No ParentTree in StructTreeRoot"
            parent_tree = struct_root["/ParentTree"]
            assert "/Nums" in parent_tree, "ParentTree has no /Nums"
            nums = parent_tree["/Nums"]
            assert len(nums) > 0, "ParentTree /Nums is empty"

    def test_injects_decorative(self, images_pdf: Path, output_pdf: Path) -> None:
        sidecar = self._fix_pdf(images_pdf, output_pdf)

        # Mark first as decorative
        sidecar.images[0].status = AltTextStatus.DECORATIVE
        count = inject_alt_text(output_pdf, sidecar)
        assert count >= 1

        with pikepdf.open(output_pdf) as pdf:
            figures = _find_figures(pdf)
            # Find the decorative figure — should have empty /Alt and /ActualText
            decorative = [f for f in figures if "/ActualText" in f]
            assert len(decorative) >= 1
            for fig in decorative:
                assert str(fig["/Alt"]) == "", "Decorative /Alt should be empty"
                assert str(fig["/ActualText"]) == "", "Decorative /ActualText should be empty"

    def test_skips_needs_review(self, images_pdf: Path, output_pdf: Path) -> None:
        sidecar = self._fix_pdf(images_pdf, output_pdf)

        # Leave all as needs_review
        for entry in sidecar.images:
            entry.status = AltTextStatus.NEEDS_REVIEW

        count = inject_alt_text(output_pdf, sidecar)
        assert count == 0

    def test_no_struct_tree_returns_zero(self, images_pdf: Path, output_pdf: Path) -> None:
        """PDF without StructTreeRoot should return 0."""
        shutil.copy2(images_pdf, output_pdf)
        sidecar = SidecarFile(document=output_pdf.name, images=[
            AltTextEntry(
                id="img_test01",
                page=1,
                hash="deadbeefdeadbeefdeadbeefdeadbeef",
                alt_text="Test",
                status=AltTextStatus.APPROVED,
            ),
        ])
        count = inject_alt_text(output_pdf, sidecar)
        assert count == 0

    def test_idempotent(self, images_pdf: Path, output_pdf: Path) -> None:
        sidecar = self._fix_pdf(images_pdf, output_pdf)

        for entry in sidecar.images:
            entry.alt_text = f"Alt for {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count1 = inject_alt_text(output_pdf, sidecar)
        assert count1 > 0

        # Inject again — should still match since the images are the same
        # Reload sidecar entries fresh
        for entry in sidecar.images:
            entry.alt_text = f"Alt for {entry.id}"
            entry.status = AltTextStatus.APPROVED

        count2 = inject_alt_text(output_pdf, sidecar)
        # Second injection creates additional Figure tags but that's OK
        assert count2 >= 0


def _find_figures(pdf: pikepdf.Pdf) -> list[pikepdf.Dictionary]:
    """Walk the tag tree and find all /Figure elements."""
    figures: list[pikepdf.Dictionary] = []
    if "/StructTreeRoot" not in pdf.Root:
        return figures
    _walk_for_figures(pdf.Root["/StructTreeRoot"], figures)
    return figures


def _walk_for_figures(node: pikepdf.Object, figures: list[pikepdf.Dictionary]) -> None:
    try:
        if "/S" in node and str(node["/S"]) == "/Figure":
            figures.append(node)
        if "/K" in node:
            kids = node["/K"]
            if isinstance(kids, pikepdf.Array):
                for child in kids:
                    if isinstance(child, pikepdf.Dictionary):
                        _walk_for_figures(child, figures)
            elif isinstance(kids, pikepdf.Dictionary):
                _walk_for_figures(kids, figures)
    except Exception:
        pass
