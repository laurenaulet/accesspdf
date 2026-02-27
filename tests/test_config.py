"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path

from accesspdf.config import AccessPDFConfig, AIConfig, OutputConfig


class TestAccessPDFConfig:
    def test_defaults(self) -> None:
        cfg = AccessPDFConfig()
        assert cfg.ai.provider == "none"
        assert cfg.ai.model == ""
        assert cfg.ai.max_tokens == 300
        assert cfg.output.suffix == "_accessible"
        assert cfg.output.report_format == "markdown"

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "accesspdf.yaml"
        config_file.write_text(
            """\
ai:
  provider: ollama
  model: llava:13b
  ollama_base_url: http://localhost:11434
  max_tokens: 500
output:
  suffix: _fixed
  report_format: json
""",
            encoding="utf-8",
        )
        cfg = AccessPDFConfig.load(config_file)
        assert cfg.ai.provider == "ollama"
        assert cfg.ai.model == "llava:13b"
        assert cfg.ai.max_tokens == 500
        assert cfg.output.suffix == "_fixed"
        assert cfg.output.report_format == "json"

    def test_load_missing_file_returns_defaults(self) -> None:
        cfg = AccessPDFConfig.load(None)
        # Falls through all candidates and returns default
        assert cfg.ai.provider == "none"

    def test_partial_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "accesspdf.yaml"
        config_file.write_text("ai:\n  provider: anthropic\n", encoding="utf-8")
        cfg = AccessPDFConfig.load(config_file)
        assert cfg.ai.provider == "anthropic"
        assert cfg.ai.max_tokens == 300  # default preserved
        assert cfg.output.report_format == "markdown"  # default preserved
