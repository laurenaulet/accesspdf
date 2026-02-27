"""Tests for AI provider registry and implementations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from accesspdf.providers import get_provider, list_available
from accesspdf.providers.base import AltTextResult, ImageContext
from accesspdf.providers.noop import NoOpProvider
from accesspdf.providers.ollama import OllamaProvider


# ── Registry tests ──────────────────────────────────────────────────────────


class TestProviderRegistry:
    def test_get_noop(self) -> None:
        provider = get_provider("noop")
        assert isinstance(provider, NoOpProvider)
        assert provider.name == "noop"

    def test_get_none_returns_noop(self) -> None:
        provider = get_provider("none")
        assert isinstance(provider, NoOpProvider)

    def test_get_ollama(self) -> None:
        provider = get_provider("ollama")
        assert isinstance(provider, OllamaProvider)
        assert provider.name == "ollama"

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent")

    def test_get_with_api_key(self) -> None:
        # Anthropic provider should accept api_key
        try:
            provider = get_provider("anthropic", api_key="test-key-123")
            assert provider.name == "anthropic"
        except ImportError:
            pytest.skip("anthropic SDK not installed")

    def test_list_available_includes_ollama(self) -> None:
        results = list_available()
        names = [name for name, _ in results]
        assert "ollama" in names
        assert "noop" in names


# ── NoOp provider tests ────────────────────────────────────────────────────


class TestNoOpProvider:
    def test_name(self) -> None:
        assert NoOpProvider().name == "noop"

    def test_generate_returns_empty(self) -> None:
        provider = NoOpProvider()
        context = ImageContext(image_bytes=b"\x89PNG\r\n")
        result = asyncio.run(provider.generate(context))
        assert isinstance(result, AltTextResult)
        assert result.alt_text == ""
        assert result.error is None

    def test_is_available(self) -> None:
        provider = NoOpProvider()
        assert asyncio.run(provider.is_available()) is True


# ── Ollama provider tests (mocked HTTP) ────────────────────────────────────


class TestOllamaProvider:
    def test_name(self) -> None:
        assert OllamaProvider().name == "ollama"

    def test_default_model(self) -> None:
        provider = OllamaProvider()
        assert provider._model == "llava"

    def test_custom_model(self) -> None:
        provider = OllamaProvider(model="llava:7b")
        assert provider._model == "llava:7b"

    def test_generate_success(self) -> None:
        provider = OllamaProvider()
        context = ImageContext(image_bytes=b"\x89PNG\r\n", page=1, caption="A chart")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "response": "A bar chart showing quarterly revenue growth.",
            "total_duration": 5000000000,
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.generate(context))

        assert result.alt_text == "A bar chart showing quarterly revenue growth."
        assert result.error is None
        assert result.confidence == 0.7

    def test_generate_error(self) -> None:
        provider = OllamaProvider()
        context = ImageContext(image_bytes=b"\x89PNG\r\n")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.generate(context))

        assert result.alt_text == ""
        assert result.error is not None
        assert "Connection refused" in result.error

    def test_is_available_success(self) -> None:
        provider = OllamaProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert asyncio.run(provider.is_available()) is True

    def test_is_available_failure(self) -> None:
        provider = OllamaProvider()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert asyncio.run(provider.is_available()) is False


# ── Cloud provider import tests ─────────────────────────────────────────────


class TestCloudProviderImports:
    """Test that cloud providers can be imported (even if SDK missing)."""

    def test_anthropic_import(self) -> None:
        try:
            from accesspdf.providers.anthropic import AnthropicProvider
            p = AnthropicProvider(api_key="test")
            assert p.name == "anthropic"
            assert asyncio.run(p.is_available()) is True
        except ImportError:
            pytest.skip("anthropic SDK not installed")

    def test_openai_import(self) -> None:
        try:
            from accesspdf.providers.openai import OpenAIProvider
            p = OpenAIProvider(api_key="test")
            assert p.name == "openai"
            assert asyncio.run(p.is_available()) is True
        except ImportError:
            pytest.skip("openai SDK not installed")

    def test_gemini_import(self) -> None:
        try:
            from accesspdf.providers.gemini import GeminiProvider
            p = GeminiProvider(api_key="test")
            assert p.name == "gemini"
            assert asyncio.run(p.is_available()) is True
        except ImportError:
            pytest.skip("google-generativeai SDK not installed")

    def test_no_key_means_unavailable(self) -> None:
        """Cloud providers without API keys should report unavailable."""
        try:
            from accesspdf.providers.anthropic import AnthropicProvider
            p = AnthropicProvider(api_key="")
            assert asyncio.run(p.is_available()) is False
        except ImportError:
            pytest.skip("anthropic SDK not installed")
