"""OpenAI (GPT-4) vision provider."""

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


class OpenAIProvider:
    """GPT-4 vision model provider via the OpenAI API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o",
        max_tokens: int = 300,
        **_kwargs: object,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "openai"

    async def generate(self, context: ImageContext) -> AltTextResult:
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=self._api_key)

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

            response = await client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{img_b64}",
                                },
                            },
                            {"type": "text", "text": user_text},
                        ],
                    },
                ],
            )

            alt_text = (response.choices[0].message.content or "").strip()
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                }

            return AltTextResult(alt_text=alt_text, confidence=0.85, usage=usage)
        except Exception as exc:
            logger.error("OpenAI generation failed: %s", exc)
            return AltTextResult(error=str(exc))

    async def is_available(self) -> bool:
        return bool(self._api_key)
