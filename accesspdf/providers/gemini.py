"""Google Gemini vision provider."""

from __future__ import annotations

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


class GeminiProvider:
    """Google Gemini vision model provider."""

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
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)

            model = genai.GenerativeModel(self._model)

            # Build image part
            image_part = {
                "mime_type": context.mime_type or "image/png",
                "data": context.image_bytes,
            }

            prompt = _SYSTEM_PROMPT + "\n\nDescribe this image for accessibility purposes."
            if context.caption:
                prompt += f'\n\nThe image has a caption: "{context.caption}"'
            if context.surrounding_text:
                prompt += f'\n\nSurrounding text: "{context.surrounding_text}"'

            response = await model.generate_content_async(
                [image_part, prompt],
                generation_config={"max_output_tokens": self._max_tokens},
            )

            alt_text = response.text.strip() if response.text else ""
            usage = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = {
                    "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                }

            return AltTextResult(alt_text=alt_text, confidence=0.8, usage=usage)
        except Exception as exc:
            logger.error("Gemini generation failed: %s", exc)
            return AltTextResult(error=str(exc))

    async def is_available(self) -> bool:
        return bool(self._api_key)
