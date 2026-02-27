"""Ollama provider — local vision model, no API key required."""

from __future__ import annotations

import base64
import logging

import httpx

from accesspdf.providers.base import AltTextResult, ImageContext

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an accessibility expert. Write concise, factual alt text for the "
    "image provided. The alt text should be suitable for a screen reader. "
    "Describe what the image shows in 1-3 sentences. Do not start with "
    "'This image shows' or 'Image of'. Just describe the content directly."
)


class OllamaProvider:
    """Local Ollama vision model provider."""

    def __init__(
        self,
        *,
        model: str = "llava:13b",
        base_url: str = "http://localhost:11434",
        max_tokens: int = 300,
        **_kwargs: object,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "ollama"

    async def generate(self, context: ImageContext) -> AltTextResult:
        try:
            img_b64 = base64.b64encode(context.image_bytes).decode()

            prompt = _SYSTEM_PROMPT
            if context.caption:
                prompt += f"\n\nThe image has a caption: \"{context.caption}\""
            if context.surrounding_text:
                prompt += f"\n\nSurrounding text: \"{context.surrounding_text}\""

            payload = {
                "model": self._model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": self._max_tokens},
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            alt_text = data.get("response", "").strip()
            return AltTextResult(
                alt_text=alt_text,
                confidence=0.7,
                usage={"total_duration_ns": data.get("total_duration", 0)},
            )
        except Exception as exc:
            logger.error("Ollama generation failed: %s", exc)
            return AltTextResult(error=str(exc))

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
