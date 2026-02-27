"""Shared data models used across the AccessPDF pipeline."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class Severity(str, enum.Enum):
    """Severity level for accessibility issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AltTextStatus(str, enum.Enum):
    """Status of an alt text entry in the sidecar file."""

    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    DECORATIVE = "decorative"


@dataclass
class AccessibilityIssue:
    """A single accessibility issue found during analysis."""

    rule: str
    severity: Severity
    message: str
    page: int | None = None
    element: str | None = None


@dataclass
class ImageInfo:
    """Information about a single image extracted from a PDF."""

    image_hash: str  # md5 hex digest of raw image bytes
    page: int
    width: int
    height: int
    color_space: str = ""
    bits_per_component: int = 8
    caption: str = ""
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)

    @property
    def short_id(self) -> str:
        """First 6 characters of the hash, used as the sidecar image id."""
        return self.image_hash[:6]


@dataclass
class TagInfo:
    """Structural tag information from the PDF tag tree."""

    tag_type: str  # e.g. "P", "H1", "Table", "Figure"
    page: int | None = None
    has_alt_text: bool = False
    alt_text: str = ""


@dataclass
class AnalysisResult:
    """Complete result of analyzing a PDF for accessibility issues."""

    source_path: Path
    page_count: int = 0
    is_tagged: bool = False
    has_lang: bool = False
    detected_lang: str = ""
    title: str = ""
    images: list[ImageInfo] = field(default_factory=list)
    tags: list[TagInfo] = field(default_factory=list)
    issues: list[AccessibilityIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)


@dataclass
class ProcessorResult:
    """Result from a single remediation processor."""

    processor_name: str
    success: bool = True
    changes_made: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RemediationResult:
    """Aggregate result from the full remediation pipeline."""

    source_path: Path
    output_path: Path
    processor_results: list[ProcessorResult] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return sum(r.changes_made for r in self.processor_results)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.processor_results)

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        for r in self.processor_results:
            for w in r.warnings:
                out.append(f"[{r.processor_name}] {w}")
        return out
