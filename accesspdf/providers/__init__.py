"""AI vision providers for alt text generation.

Provider registry — use ``get_provider()`` to obtain an ``AltTextGenerator``
by name, and ``list_available()`` to check which providers are configured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from accesspdf.providers.base import AltTextGenerator

logger = logging.getLogger(__name__)

# Map of provider name → module path, class name
_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "ollama": ("accesspdf.providers.ollama", "OllamaProvider"),
    "anthropic": ("accesspdf.providers.anthropic", "AnthropicProvider"),
    "openai": ("accesspdf.providers.openai", "OpenAIProvider"),
    "gemini": ("accesspdf.providers.gemini", "GeminiProvider"),
    "noop": ("accesspdf.providers.noop", "NoOpProvider"),
    "none": ("accesspdf.providers.noop", "NoOpProvider"),
}


def get_provider(name: str, *, api_key: str | None = None, **kwargs: Any) -> AltTextGenerator:
    """Create a provider instance by name.

    Raises ``ValueError`` if the provider name is unknown.
    Raises ``ImportError`` if the required SDK is not installed.
    """
    name = name.lower().strip()
    if name not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown provider: {name!r}. "
            f"Available: {', '.join(n for n in _PROVIDER_MAP if n != 'none')}"
        )

    module_path, class_name = _PROVIDER_MAP[name]
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    # Pass api_key to providers that accept it
    init_kwargs: dict[str, Any] = dict(kwargs)
    if api_key is not None:
        init_kwargs["api_key"] = api_key

    return cls(**init_kwargs)


def list_available() -> list[tuple[str, bool]]:
    """Return (provider_name, is_available) for all known providers.

    Checks each provider's ``is_available()`` method. Providers whose SDK
    is not installed are reported as unavailable.
    """
    results: list[tuple[str, bool]] = []
    for name in _PROVIDER_MAP:
        if name == "none":
            continue
        try:
            provider = get_provider(name)
            available = _run_async(provider.is_available())
        except (ImportError, Exception):
            available = False
        results.append((name, available))
    return results


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine, handling the case where an event loop is already running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context (e.g. FastAPI) — create a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=10)
    else:
        return asyncio.run(coro)
