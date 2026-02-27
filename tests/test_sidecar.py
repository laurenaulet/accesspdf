"""Tests for sidecar file read/write system."""

from __future__ import annotations

from pathlib import Path

import pytest

from accesspdf.alttext.sidecar import AltTextEntry, SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus, ImageInfo


class TestAltTextEntry:
    def test_is_actionable_approved(self) -> None:
        entry = AltTextEntry(
            id="img_abc123", page=1, hash="abc123" * 5,
            status=AltTextStatus.APPROVED,
        )
        assert entry.is_actionable is True

    def test_is_actionable_decorative(self) -> None:
        entry = AltTextEntry(
            id="img_abc123", page=1, hash="abc123" * 5,
            status=AltTextStatus.DECORATIVE,
        )
        assert entry.is_actionable is True

    def test_is_not_actionable_needs_review(self) -> None:
        entry = AltTextEntry(
            id="img_abc123", page=1, hash="abc123" * 5,
            status=AltTextStatus.NEEDS_REVIEW,
        )
        assert entry.is_actionable is False


class TestSidecarFile:
    def _make_image(self, hash_val: str = "a3f8c2d901abcdef", page: int = 1) -> ImageInfo:
        return ImageInfo(image_hash=hash_val, page=page, width=100, height=200)

    def test_upsert_new_entry(self) -> None:
        sc = SidecarFile(document="test.pdf")
        img = self._make_image()
        entry = sc.upsert(img)
        assert entry.id == "img_a3f8c2"
        assert entry.hash == "a3f8c2d901abcdef"
        assert entry.page == 1
        assert entry.status == AltTextStatus.NEEDS_REVIEW
        assert len(sc.images) == 1

    def test_upsert_updates_existing(self) -> None:
        sc = SidecarFile(document="test.pdf")
        img = self._make_image()
        sc.upsert(img)
        sc.upsert(img, ai_draft="A bar chart showing data.")
        assert len(sc.images) == 1
        assert sc.images[0].ai_draft == "A bar chart showing data."

    def test_upsert_preserves_existing_fields(self) -> None:
        sc = SidecarFile(document="test.pdf")
        img = self._make_image()
        sc.upsert(img, ai_draft="draft text")
        sc.upsert(img, alt_text="final text")
        assert sc.images[0].ai_draft == "draft text"
        assert sc.images[0].alt_text == "final text"

    def test_get_entry_by_hash(self) -> None:
        sc = SidecarFile(document="test.pdf")
        img = self._make_image()
        sc.upsert(img)
        found = sc.get_entry("a3f8c2d901abcdef")
        assert found is not None
        assert found.page == 1

    def test_get_entry_not_found(self) -> None:
        sc = SidecarFile(document="test.pdf")
        assert sc.get_entry("nonexistent") is None

    def test_get_entry_by_id(self) -> None:
        sc = SidecarFile(document="test.pdf")
        sc.upsert(self._make_image())
        found = sc.get_entry_by_id("img_a3f8c2")
        assert found is not None

    def test_approved_entries(self) -> None:
        sc = SidecarFile(document="test.pdf")
        sc.upsert(self._make_image("aaa111bbb222"), status=AltTextStatus.APPROVED)
        sc.upsert(self._make_image("ccc333ddd444"), status=AltTextStatus.NEEDS_REVIEW)
        sc.upsert(self._make_image("eee555fff666"), status=AltTextStatus.APPROVED)
        approved = list(sc.approved_entries())
        assert len(approved) == 2

    def test_needs_review_entries(self) -> None:
        sc = SidecarFile(document="test.pdf")
        sc.upsert(self._make_image("aaa111bbb222"), status=AltTextStatus.APPROVED)
        sc.upsert(self._make_image("ccc333ddd444"), status=AltTextStatus.NEEDS_REVIEW)
        needs = list(sc.needs_review_entries())
        assert len(needs) == 1

    def test_stats(self) -> None:
        sc = SidecarFile(document="test.pdf")
        sc.upsert(self._make_image("aaa111"), status=AltTextStatus.APPROVED)
        sc.upsert(self._make_image("bbb222"), status=AltTextStatus.NEEDS_REVIEW)
        sc.upsert(self._make_image("ccc333"), status=AltTextStatus.DECORATIVE)
        stats = sc.stats
        assert stats["total"] == 3
        assert stats["approved"] == 1
        assert stats["needs_review"] == 1
        assert stats["decorative"] == 1


class TestSidecarManager:
    def test_sidecar_path_for(self) -> None:
        path = SidecarManager.sidecar_path_for(Path("docs/thesis.pdf"))
        assert path == Path("docs/thesis.alttext.yaml")

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        sc = SidecarFile(document="roundtrip.pdf")
        img = ImageInfo(image_hash="deadbeef01234567", page=2, width=50, height=50)
        sc.upsert(img, ai_draft="AI draft text", alt_text="Approved text",
                   status=AltTextStatus.APPROVED)

        path = tmp_path / "roundtrip.alttext.yaml"
        SidecarManager.save(sc, path)

        loaded = SidecarManager.load(path)
        assert loaded.document == "roundtrip.pdf"
        assert len(loaded.images) == 1
        entry = loaded.images[0]
        assert entry.hash == "deadbeef01234567"
        assert entry.ai_draft == "AI draft text"
        assert entry.alt_text == "Approved text"
        assert entry.status == AltTextStatus.APPROVED

    def test_load_sample_sidecar(self, sample_sidecar_yaml: Path) -> None:
        sc = SidecarManager.load(sample_sidecar_yaml)
        assert sc.document == "test.pdf"
        assert len(sc.images) == 3
        assert sc.images[0].status == AltTextStatus.NEEDS_REVIEW
        assert sc.images[1].status == AltTextStatus.APPROVED
        assert sc.images[2].status == AltTextStatus.DECORATIVE

    def test_load_empty_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.alttext.yaml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            SidecarManager.load(path)

    def test_load_or_create_new(self, tmp_path: Path) -> None:
        pdf_path = tmp_path / "new.pdf"
        pdf_path.touch()
        sc, sc_path = SidecarManager.load_or_create(pdf_path)
        assert sc.document == "new.pdf"
        assert len(sc.images) == 0
        assert sc_path == tmp_path / "new.alttext.yaml"

    def test_load_or_create_existing(self, tmp_path: Path, sample_sidecar_yaml: Path) -> None:
        # Rename to match expected pattern
        pdf_path = tmp_path / "test.pdf"
        pdf_path.touch()
        sc, sc_path = SidecarManager.load_or_create(pdf_path)
        assert sc.document == "test.pdf"
        assert len(sc.images) == 3

    def test_idempotent_save(self, tmp_path: Path) -> None:
        """Saving the same sidecar twice produces identical files."""
        sc = SidecarFile(document="idem.pdf")
        img = ImageInfo(image_hash="abcdef0123456789", page=1, width=10, height=10)
        sc.upsert(img, alt_text="test")

        path = tmp_path / "idem.alttext.yaml"
        SidecarManager.save(sc, path)
        content1 = path.read_text(encoding="utf-8")

        SidecarManager.save(sc, path)
        content2 = path.read_text(encoding="utf-8")

        assert content1 == content2
