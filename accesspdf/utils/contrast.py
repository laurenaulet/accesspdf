"""WCAG 2.1 contrast ratio utilities.

Implements the relative luminance and contrast ratio calculations defined in
WCAG 2.1 Success Criterion 1.4.3 (Contrast — Minimum).
"""

from __future__ import annotations


def _srgb_to_linear(v: float) -> float:
    """Convert an sRGB channel (0-1) to linear light."""
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(r: int, g: int, b: int) -> float:
    """Compute relative luminance for an sRGB color (0-255 per channel).

    Per WCAG 2.1: L = 0.2126*R + 0.7152*G + 0.0722*B
    where R, G, B are linearized sRGB values.
    """
    rl = _srgb_to_linear(r / 255.0)
    gl = _srgb_to_linear(g / 255.0)
    bl = _srgb_to_linear(b / 255.0)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(color1: tuple[int, int, int], color2: tuple[int, int, int]) -> float:
    """Compute the WCAG contrast ratio between two sRGB colors.

    Returns a value between 1.0 (identical) and 21.0 (black on white).
    """
    l1 = relative_luminance(*color1)
    l2 = relative_luminance(*color2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def passes_aa(ratio: float, *, large_text: bool = False) -> bool:
    """Check whether a contrast ratio meets WCAG AA.

    Normal text: 4.5:1 minimum.
    Large text (>=18pt or >=14pt bold): 3:1 minimum.
    """
    threshold = 3.0 if large_text else 4.5
    return ratio >= threshold


def _clamp(v: float) -> int:
    return max(0, min(255, round(v)))


def parse_pdf_color(operands: list[float], color_space: str) -> tuple[int, int, int]:
    """Convert PDF color operands to an (R, G, B) tuple (0-255).

    Supports:
    - ``rgb`` (rg/RG): 3 floats 0-1
    - ``gray`` (g/G): 1 float 0-1
    - ``cmyk`` (k/K): 4 floats 0-1
    """
    cs = color_space.lower()
    if cs == "rgb" and len(operands) >= 3:
        return (
            _clamp(operands[0] * 255),
            _clamp(operands[1] * 255),
            _clamp(operands[2] * 255),
        )
    elif cs == "gray" and len(operands) >= 1:
        v = _clamp(operands[0] * 255)
        return (v, v, v)
    elif cs == "cmyk" and len(operands) >= 4:
        c, m, y, k = operands[0], operands[1], operands[2], operands[3]
        r = _clamp(255 * (1 - c) * (1 - k))
        g = _clamp(255 * (1 - m) * (1 - k))
        b = _clamp(255 * (1 - y) * (1 - k))
        return (r, g, b)
    # Fallback: black
    return (0, 0, 0)
