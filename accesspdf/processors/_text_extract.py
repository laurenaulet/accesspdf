"""Shared pdfminer text extraction used by multiple processors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import (
    LAParams,
    LTAnno,
    LTChar,
    LTFigure,
    LTLine,
    LTRect,
    LTTextBox,
    LTTextLine,
)


@dataclass
class TextBlock:
    """A block of text with font information and position."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    font_name: str
    font_size: float
    is_bold: bool


@dataclass
class RulingLine:
    """A horizontal or vertical line (for table detection)."""

    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    orientation: str  # "horizontal" or "vertical"


def extract_text_blocks(pdf_path: Path) -> list[TextBlock]:
    """Extract all text blocks with font metadata from all pages."""
    blocks: list[TextBlock] = []
    params = LAParams(line_margin=0.5, word_margin=0.1, boxes_flow=0.5)

    for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=params), 1):
        _extract_from_element(page_layout, page_num, blocks)

    return blocks


def _extract_from_element(
    element: object, page: int, blocks: list[TextBlock]
) -> None:
    """Recursively extract TextBlocks from layout elements."""
    if isinstance(element, LTTextBox):
        for line in element:
            if isinstance(line, LTTextLine):
                text = line.get_text().strip()
                if not text:
                    continue
                font_name, font_size = _dominant_font_from_line(line)
                blocks.append(TextBlock(
                    text=text,
                    page=page,
                    x0=line.x0,
                    y0=line.y0,
                    x1=line.x1,
                    y1=line.y1,
                    font_name=font_name,
                    font_size=font_size,
                    is_bold=is_bold_font(font_name),
                ))
        return

    if isinstance(element, LTFigure):
        for child in element:
            _extract_from_element(child, page, blocks)
    elif hasattr(element, "__iter__"):
        for child in element:  # type: ignore[union-attr]
            _extract_from_element(child, page, blocks)


def extract_ruling_lines(pdf_path: Path) -> list[RulingLine]:
    """Extract horizontal and vertical ruling lines from all pages."""
    lines: list[RulingLine] = []
    params = LAParams()

    for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=params), 1):
        _extract_lines_from_element(page_layout, page_num, lines)

    return lines


def _extract_lines_from_element(
    element: object, page: int, lines: list[RulingLine]
) -> None:
    """Recursively find LTLine and LTRect elements."""
    if isinstance(element, LTLine):
        dx = abs(element.x1 - element.x0)
        dy = abs(element.y1 - element.y0)
        if dx > dy:
            orientation = "horizontal"
        else:
            orientation = "vertical"
        lines.append(RulingLine(
            x0=element.x0, y0=element.y0,
            x1=element.x1, y1=element.y1,
            page=page, orientation=orientation,
        ))
    elif isinstance(element, LTRect):
        # A rect defines 4 lines — extract the borders
        lines.append(RulingLine(
            x0=element.x0, y0=element.y0,
            x1=element.x1, y1=element.y0,
            page=page, orientation="horizontal",
        ))
        lines.append(RulingLine(
            x0=element.x0, y0=element.y1,
            x1=element.x1, y1=element.y1,
            page=page, orientation="horizontal",
        ))
        lines.append(RulingLine(
            x0=element.x0, y0=element.y0,
            x1=element.x0, y1=element.y1,
            page=page, orientation="vertical",
        ))
        lines.append(RulingLine(
            x0=element.x1, y0=element.y0,
            x1=element.x1, y1=element.y1,
            page=page, orientation="vertical",
        ))

    if hasattr(element, "__iter__") and not isinstance(element, (LTLine, LTRect)):
        for child in element:  # type: ignore[union-attr]
            _extract_lines_from_element(child, page, lines)


def extract_full_text(pdf_path: Path) -> str:
    """Extract plain text from entire PDF (for language detection)."""
    return extract_text(str(pdf_path))


def is_bold_font(fontname: str) -> bool:
    """Heuristic: check if font name contains Bold/Black/Heavy indicators."""
    lower = fontname.lower()
    return any(kw in lower for kw in ("bold", "black", "heavy", "demi"))


def _dominant_font_from_line(line: LTTextLine) -> tuple[str, float]:
    """Return the most common (fontname, fontsize) pair from a text line."""
    chars: list[tuple[str, float]] = []
    for char in line:
        if isinstance(char, LTChar):
            chars.append((char.fontname, char.size))

    if not chars:
        return ("Unknown", 12.0)

    # Return the most common pair
    from collections import Counter
    counter = Counter(chars)
    (font_name, font_size), _ = counter.most_common(1)[0]
    return (font_name, round(font_size, 1))
