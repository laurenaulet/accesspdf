"""Google Gemini vision provider — uses REST API directly (no SDK install needed)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import time

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
_MAX_RETRIES = 5
_INITIAL_WAIT = 15  # seconds

# Minimum seconds between API requests — prevents bursting.
# Gemini free tier is 15 RPM; 5s gap = 12 RPM max, safely under limit.
_MIN_REQUEST_INTERVAL = 5.0


class _Throttle:
    """Simple async throttle — enforces a minimum gap between requests.

    Unlike a sliding-window rate limiter, this prevents ALL bursting
    by serializing requests with a guaranteed wait between each one.
    """

    def __init__(self, min_interval: float = _MIN_REQUEST_INTERVAL) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request: float = 0.0

    async def wait(self) -> None:
        """Wait until enough time has passed since the last request."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                logger.debug("Throttle: waiting %.1fs before next request", wait)
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


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
        self._client: httpx.AsyncClient | None = None
        self._throttle = _Throttle()

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared httpx client (connection pooling)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

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
        if context.document_context:
            prompt += f'\n\nDocument context: "{context.document_context}"'
        if context.document_title:
            prompt += f'\n\nDocument title: "{context.document_title}"'

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
        client = await self._get_client()
        for attempt in range(_MAX_RETRIES + 1):
            try:
                # Throttle: enforce minimum gap between requests
                await self._throttle.wait()

                resp = await client.post(url, content=body, headers=headers)

                # Retry on rate limit
                if resp.status_code == 429 and attempt < _MAX_RETRIES:
                    wait = _retry_wait(resp, attempt)
                    logger.warning(
                        "Gemini rate limited (429), waiting %.0fs before retry %d/%d",
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

    async def preflight(self) -> str | None:
        """Quick API check — returns None if OK, or an error message.

        Sends a tiny text-only request to verify the key works and
        the rate limit isn't exhausted before committing to a batch.
        """
        if not self._api_key:
            return (
                "No API key. Set GOOGLE_API_KEY or pass --api-key. "
                "Get a free key at https://aistudio.google.com/apikey"
            )

        payload = {
            "contents": [{"parts": [{"text": "Say OK"}]}],
            "generationConfig": {"maxOutputTokens": 5},
        }
        url = f"{_API_BASE}/{self._model}:generateContent?key={self._api_key}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}

        try:
            client = await self._get_client()
            resp = await client.post(url, content=body, headers=headers)

            if resp.status_code == 429:
                wait = _friendly_wait_message(resp)
                return (
                    f"Gemini rate limit reached. {wait}\n"
                    "The free tier allows 15 requests/minute and 1,500/day. "
                    "Wait a bit and try again."
                )
            if resp.status_code == 403:
                return "API key rejected (403 Forbidden). Check your key at https://aistudio.google.com/apikey"
            resp.raise_for_status()
            return None  # All good!
        except Exception as exc:
            return f"Cannot reach Gemini API: {exc}"

    async def is_available(self) -> bool:
        return bool(self._api_key)


def _friendly_wait_message(resp: httpx.Response) -> str:
    """Try to extract a human-readable wait time from a 429 response."""
    try:
        data = resp.json()
        details = data.get("error", {}).get("details", [])
        for d in details:
            if "retryDelay" in d:
                delay_str = d["retryDelay"]
                secs = float(delay_str.rstrip("s"))
                if secs > 60:
                    return f"Try again in about {int(secs // 60)} minute(s)."
                return f"Try again in about {int(secs)} seconds."
    except Exception:
        pass
    return "Try again in a minute or two."


def _retry_wait(resp: httpx.Response, attempt: int) -> float:
    """Extract retry delay from response, or use exponential backoff with jitter."""
    try:
        data = resp.json()
        details = data.get("error", {}).get("details", [])
        for d in details:
            if "retryDelay" in d:
                delay_str = d["retryDelay"]  # e.g. "20s" or "20.5s"
                return float(delay_str.rstrip("s")) + random.uniform(1, 3)
    except Exception:
        pass
    # Fallback: exponential backoff with jitter to avoid thundering herd
    base = _INITIAL_WAIT * (2 ** attempt)
    return base + random.uniform(0, base * 0.5)
