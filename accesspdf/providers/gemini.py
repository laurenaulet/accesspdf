"""Google Gemini vision provider — uses REST API directly (no SDK install needed)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

import httpx

from accesspdf.providers.base import AltTextResult, ImageContext

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_SYSTEM_PROMPT = (
    "You are an accessibility expert. Write concise, factual alt text for the "
    "image provided. The alt text should be suitable for a screen reader. "
    "Describe what the image shows in 1-3 sentences. Do not start with "
    "'This image shows' or 'Image of'. Just describe the content directly."
)

# Retry settings for rate limiting (429 errors)
_MAX_RETRIES = 3
_INITIAL_WAIT = 5  # seconds


class GeminiProvider:
    """Google Gemini vision model provider (free tier, no SDK required)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        max_tokens: int = 300,
        **_kwargs: object,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "gemini"

    async def generate(self, context: ImageContext) -> AltTextResult:
        if not self._api_key:
            return AltTextResult(
                error="No API key. Set GOOGLE_API_KEY or pass --api-key. "
                      "Get a free key at https://aistudio.google.com/apikey"
            )

        img_b64 = base64.b64encode(context.image_bytes).decode()
        mime_type = context.mime_type or "image/png"

        prompt = _SYSTEM_PROMPT + "\n\nDescribe this image for accessibility purposes."
        if context.caption:
            prompt += f'\n\nThe image has a caption: "{context.caption}"'
        if context.surrounding_text:
            prompt += f'\n\nSurrounding text: "{context.surrounding_text}"'

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": img_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": self._max_tokens,
            },
        }

        url = f"{_API_BASE}/{self._model}:generateContent?key={self._api_key}"

        # Serialize to bytes so httpx sends Content-Length (Google rejects chunked)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}

        # Retry loop for rate limiting
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(url, content=body, headers=headers)

                    # Retry on rate limit
                    if resp.status_code == 429 and attempt < _MAX_RETRIES:
                        wait = _retry_wait(resp, attempt)
                        logger.info(
                            "Gemini rate limited, waiting %ds before retry %d/%d",
                            wait, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                # Extract text from response
                candidates = data.get("candidates", [])
                if not candidates:
                    return AltTextResult(error="Gemini returned no candidates.")

                parts = candidates[0].get("content", {}).get("parts", [])
                alt_text = parts[0].get("text", "").strip() if parts else ""

                usage = {}
                usage_meta = data.get("usageMetadata", {})
                if usage_meta:
                    usage = {
                        "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                        "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                    }

                return AltTextResult(alt_text=alt_text, confidence=0.8, usage=usage)

            except httpx.HTTPStatusError as exc:
                error_body = exc.response.text
                logger.error("Gemini API error (%s): %s", exc.response.status_code, error_body)
                return AltTextResult(error=f"Gemini API error {exc.response.status_code}: {error_body}")
            except Exception as exc:
                logger.error("Gemini generation failed: %s", exc)
                return AltTextResult(error=str(exc))

        # If we exhausted all retries
        return AltTextResult(
            error="Gemini rate limit: too many requests. Wait a minute and try again, "
                  "or check your API key at https://aistudio.google.com/apikey"
        )

    async def is_available(self) -> bool:
        return bool(self._api_key)


def _retry_wait(resp: httpx.Response, attempt: int) -> int:
    """Extract retry delay from response, or use exponential backoff."""
    try:
        data = resp.json()
        details = data.get("error", {}).get("details", [])
        for d in details:
            if "retryDelay" in d:
                delay_str = d["retryDelay"]  # e.g. "20s" or "20.5s"
                return int(float(delay_str.rstrip("s"))) + 1
    except Exception:
        pass
    # Fallback: exponential backoff
    return _INITIAL_WAIT * (2 ** attempt)
