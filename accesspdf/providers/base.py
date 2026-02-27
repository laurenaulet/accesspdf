"""Base protocol and shared types for AI vision providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ImageContext:
    """Context passed to an AI provider along with the image bytes."""

    image_bytes: bytes
    mime_type: str = "image/png"
    caption: str = ""
    surrounding_text: str = ""
    page: int = 0
    document_title: str = ""


@dataclass
class AltTextResult:
    """Result returned by an AI provider after generating alt text."""

    alt_text: str = ""
    confidence: float = 0.0
    is_decorative: bool = False
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)  # token counts, etc.


@runtime_checkable
class AltTextGenerator(Protocol):
    """Interface that every AI vision provider must implement.

    Providers live in ``accesspdf/providers/`` — one file per provider.
    No provider-specific code should exist outside that directory.
    """

    @property
    def name(self) -> str:
        """Provider identifier (e.g. 'anthropic', 'ollama')."""
        ...

    async def generate(self, context: ImageContext) -> AltTextResult:
        """Generate alt text for a single image.

        Returns an AltTextResult.  On failure the result should carry an
        ``error`` message rather than raising.
        """
        ...

    async def is_available(self) -> bool:
        """Check whether the provider is reachable / configured.

        For cloud providers this checks for an API key in the environment.
        For Ollama it pings the local server.
        """
        ...
