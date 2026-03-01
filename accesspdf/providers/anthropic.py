"""Anthropic (Claude) vision provider."""

from __future__ import annotations

import base64
import logging
import os

from accesspdf.providers.base import AltTextResult, ImageContext

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an accessibility expert. Write concise, factual alt text for the "
    "image provided. The alt text should be suitable for a screen reader. "
    "Describe what the image shows in 1-3 sentences. Do not start with "
    "'This image shows' or 'Image of'. Just describe the content directly."
)


class AnthropicProvider:
    """Claude vision model provider via the Anthropic API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 300,
        **_kwargs: object,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "anthropic"

    async def generate(self, context: ImageContext) -> AltTextResult:
        try:
            import anthropic
        except ImportError:
            return AltTextResult(
                error="Anthropic SDK not installed. Run: pip install anthropic"
            )

        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)

            img_b64 = base64.b64encode(context.image_bytes).decode()
            media_type = context.mime_type or "image/png"

            user_text = "Describe this image for accessibility purposes."
            if context.caption:
                user_text += f'\n\nThe image has a caption: "{context.caption}"'
            if context.surrounding_text:
                user_text += f'\n\nSurrounding text: "{context.surrounding_text}"'
            if context.document_context:
                user_text += f'\n\nDocument context: "{context.document_context}"'
            if context.document_title:
                user_text += f'\n\nDocument title: "{context.document_title}"'

            message = await client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }],
            )

            if not message.content:
                return AltTextResult(error="Anthropic returned empty response")
            first_block = message.content[0]
            if not hasattr(first_block, "text"):
                return AltTextResult(error="Unexpected response format from Anthropic")
            alt_text = first_block.text.strip()
            usage = {}
            if message.usage:
                usage = {
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens,
                }

            return AltTextResult(alt_text=alt_text, confidence=0.85, usage=usage)
        except Exception as exc:
            logger.error("Anthropic generation failed: %s", exc)
            return AltTextResult(error=str(exc))

    async def is_available(self) -> bool:
        return bool(self._api_key)
