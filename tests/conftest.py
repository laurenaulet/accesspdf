"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.generate import CORPUS_DIR, generate_all


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Alias for pytest's tmp_path fixture."""
    return tmp_path


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    """Ensure test PDFs exist and return the corpus directory."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    generate_all()
    return CORPUS_DIR


@pytest.fixture(scope="session")
def simple_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "simple.pdf"


@pytest.fixture(scope="session")
def headings_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "headings.pdf"


@pytest.fixture(scope="session")
def tables_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "tables.pdf"


@pytest.fixture(scope="session")
def links_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "links.pdf"


@pytest.fixture(scope="session")
def multicolumn_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "multicolumn.pdf"


@pytest.fixture(scope="session")
def images_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "images.pdf"


@pytest.fixture(scope="session")
def low_contrast_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "low_contrast.pdf"


@pytest.fixture(scope="session")
def ambiguous_links_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "ambiguous_links.pdf"


@pytest.fixture(scope="session")
def scanned_pdf(corpus_dir: Path) -> Path:
    return corpus_dir / "scanned.pdf"


@pytest.fixture
def output_pdf(tmp_path: Path) -> Path:
    """Temporary output path for remediated PDFs."""
    return tmp_path / "output.pdf"


@pytest.fixture
def sample_sidecar_yaml(tmp_path: Path) -> Path:
    """Write a sample sidecar YAML and return its path."""
    content = """\
document: test.pdf
generated: '2026-01-15T10:00:00+00:00'
images:
- id: img_a3f8c2
  page: 1
  hash: a3f8c2d901abcdef1234567890abcdef
  caption: 'Figure 1: Sample chart'
  ai_draft: Bar chart showing sales data.
  alt_text: ''
  status: needs_review
- id: img_b91d44
  page: 3
  hash: b91d44ee02abcdef1234567890abcdef
  caption: ''
  ai_draft: ''
  alt_text: University logo
  status: approved
- id: img_cc0011
  page: 5
  hash: cc0011ff03abcdef1234567890abcdef
  caption: ''
  ai_draft: ''
  alt_text: ''
  status: decorative
"""
    path = tmp_path / "test.alttext.yaml"
    path.write_text(content, encoding="utf-8")
    return path
