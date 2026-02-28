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
        model: str = "llava",
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
            if context.document_context:
                prompt += f"\n\nDocument context: \"{context.document_context}\""
            if context.document_title:
                prompt += f"\n\nDocument title: \"{context.document_title}\""

            payload = {
                "model": self._model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": self._max_tokens},
            }

            # First image can take a long time (model loads CLIP weights)
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)

                if resp.status_code != 200:
                    # Extract the actual error message from Ollama
                    try:
                        body = resp.json()
                        err_msg = body.get("error", resp.text)
                    except Exception:
                        err_msg = resp.text
                    error = f"Ollama error ({resp.status_code}): {err_msg}"
                    logger.error(error)
                    return AltTextResult(error=error)

                data = resp.json()

            alt_text = data.get("response", "").strip()
            return AltTextResult(
                alt_text=alt_text,
                confidence=0.7,
                usage={"total_duration_ns": data.get("total_duration", 0)},
            )
        except httpx.ConnectError:
            error = (
                "Cannot connect to Ollama. Is it running? "
                "Start it with: ollama serve"
            )
            logger.error(error)
            return AltTextResult(error=error)
        except Exception as exc:
            logger.error("Ollama generation failed: %s", exc)
            return AltTextResult(error=str(exc))

    async def preflight(self) -> str | None:
        """Check Ollama is running and the model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check server is up
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    return "Cannot reach Ollama server. Is it running? Start with: ollama serve"

                # Check model is pulled
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Ollama model names can be "llava:latest" — check prefix match
                model_found = any(
                    m == self._model or m.startswith(self._model + ":")
                    for m in models
                )
                if not model_found:
                    available = ", ".join(m.split(":")[0] for m in models[:5]) or "none"
                    return (
                        f"Model '{self._model}' not found. "
                        f"Pull it first: ollama pull {self._model}\n"
                        f"Available models: {available}"
                    )
                return None  # All good
        except httpx.ConnectError:
            return "Cannot connect to Ollama. Is it running? Start with: ollama serve"
        except Exception as exc:
            return f"Ollama check failed: {exc}"

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
