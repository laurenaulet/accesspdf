"""No-op provider — returns empty results, flags images for manual review."""

from __future__ import annotations

from accesspdf.providers.base import AltTextResult, ImageContext


class NoOpProvider:
    """Provider that does nothing — used when ``provider: none``."""

    @property
    def name(self) -> str:
        return "noop"

    async def generate(self, context: ImageContext) -> AltTextResult:
        return AltTextResult()

    async def is_available(self) -> bool:
        return True
