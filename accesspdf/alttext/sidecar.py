"""Sidecar YAML file management for alt text entries.

The sidecar file (``document.alttext.yaml``) is the single source of truth for
all alt text in a document.  It is created on first analysis, updated by AI
providers and manual edits, and consumed by the Writer to inject approved
alt text into the output PDF.

Image IDs are based on ``md5(image_bytes)`` so they survive PDF re-exports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import yaml
from pydantic import BaseModel, Field

from accesspdf.models import AltTextStatus, ImageInfo


class AltTextEntry(BaseModel):
    """A single image entry in the sidecar file."""

    id: str  # img_{hash[:6]}
    page: int
    hash: str  # full md5 hex digest
    caption: str = ""
    ai_draft: str = ""
    alt_text: str = ""
    status: AltTextStatus = AltTextStatus.NEEDS_REVIEW

    @property
    def is_actionable(self) -> bool:
        """True if the entry has approved or decorative status."""
        return self.status in (AltTextStatus.APPROVED, AltTextStatus.DECORATIVE)


class SidecarFile(BaseModel):
    """In-memory representation of a ``.alttext.yaml`` sidecar file."""

    document: str
    generated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    images: list[AltTextEntry] = Field(default_factory=list)

    def get_entry(self, image_hash: str) -> AltTextEntry | None:
        """Look up an entry by its full md5 hash."""
        for entry in self.images:
            if entry.hash == image_hash:
                return entry
        return None

    def get_entry_by_id(self, entry_id: str) -> AltTextEntry | None:
        """Look up an entry by its short id (e.g. 'img_a3f8c2')."""
        for entry in self.images:
            if entry.id == entry_id:
                return entry
        return None

    def upsert(self, image: ImageInfo, *, ai_draft: str = "", alt_text: str = "",
               status: AltTextStatus | None = None) -> AltTextEntry:
        """Insert or update an entry for the given image.

        If an entry with the same hash already exists it is updated (preserving
        fields that are not explicitly provided).  Otherwise a new entry is
        appended.
        """
        existing = self.get_entry(image.image_hash)
        if existing is not None:
            if ai_draft:
                existing.ai_draft = ai_draft
            if alt_text:
                existing.alt_text = alt_text
            if status is not None:
                existing.status = status
            return existing

        entry = AltTextEntry(
            id=f"img_{image.short_id}",
            page=image.page,
            hash=image.image_hash,
            caption=image.caption,
            ai_draft=ai_draft,
            alt_text=alt_text,
            status=status or AltTextStatus.NEEDS_REVIEW,
        )
        self.images.append(entry)
        return entry

    def approved_entries(self) -> Iterator[AltTextEntry]:
        """Yield only entries with ``status == approved``."""
        for entry in self.images:
            if entry.status == AltTextStatus.APPROVED:
                yield entry

    def needs_review_entries(self) -> Iterator[AltTextEntry]:
        """Yield entries still awaiting human review."""
        for entry in self.images:
            if entry.status == AltTextStatus.NEEDS_REVIEW:
                yield entry

    @property
    def stats(self) -> dict[str, int]:
        """Count of entries by status."""
        counts: dict[str, int] = {"total": len(self.images)}
        for status in AltTextStatus:
            counts[status.value] = sum(
                1 for e in self.images if e.status == status
            )
        return counts


class SidecarManager:
    """Handles reading and writing sidecar YAML files on disk.

    Usage::

        manager = SidecarManager()
        sidecar = manager.load(Path("thesis.alttext.yaml"))
        # ... mutate sidecar ...
        manager.save(sidecar, Path("thesis.alttext.yaml"))
    """

    @staticmethod
    def sidecar_path_for(pdf_path: Path) -> Path:
        """Derive the sidecar file path from a PDF path.

        ``thesis.pdf`` -> ``thesis.alttext.yaml``
        """
        return pdf_path.with_suffix(".alttext.yaml")

    @staticmethod
    def load(path: Path) -> SidecarFile:
        """Load a sidecar file from disk."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            raise ValueError(f"Sidecar file is empty: {path}")
        return SidecarFile.model_validate(raw)

    @staticmethod
    def save(sidecar: SidecarFile, path: Path) -> None:
        """Write a sidecar file to disk as YAML."""
        data = sidecar.model_dump(mode="json")
        # Convert datetime to ISO string for clean YAML
        if isinstance(data.get("generated"), str):
            pass  # already string from mode="json"

        yaml_str = yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        path.write_text(yaml_str, encoding="utf-8")

    @classmethod
    def load_or_create(cls, pdf_path: Path) -> tuple[SidecarFile, Path]:
        """Load an existing sidecar or create a new empty one.

        Returns the SidecarFile and the path it was loaded from / will be
        saved to.
        """
        sidecar_path = cls.sidecar_path_for(pdf_path)
        if sidecar_path.is_file():
            return cls.load(sidecar_path), sidecar_path

        sidecar = SidecarFile(document=pdf_path.name)
        return sidecar, sidecar_path
