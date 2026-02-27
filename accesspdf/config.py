"""Pydantic configuration model with YAML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG_NAME = "accesspdf.yaml"


class AIConfig(BaseModel):
    """AI provider settings."""

    provider: Literal["anthropic", "openai", "gemini", "ollama", "none"] = "none"
    model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    max_tokens: int = 300


class OutputConfig(BaseModel):
    """Output file settings."""

    suffix: str = "_accessible"
    report_format: Literal["json", "markdown", "html"] = "markdown"


class AccessPDFConfig(BaseModel):
    """Top-level configuration for AccessPDF."""

    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> AccessPDFConfig:
        """Load config from a YAML file.

        Search order when *path* is None:
          1. ./accesspdf.yaml
          2. ~/.config/accesspdf/accesspdf.yaml

        Returns default config if no file is found.
        """
        if path is not None:
            return cls._from_yaml(path)

        candidates = [
            Path.cwd() / _DEFAULT_CONFIG_NAME,
            Path.home() / ".config" / "accesspdf" / _DEFAULT_CONFIG_NAME,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return cls._from_yaml(candidate)

        return cls()

    @classmethod
    def _from_yaml(cls, path: Path) -> AccessPDFConfig:
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)
