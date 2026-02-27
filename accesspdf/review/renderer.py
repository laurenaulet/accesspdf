"""Terminal image rendering using half-block characters.

Renders Pillow Images as colored text using Unicode half-block characters
(upper half block U+2580). Each character cell represents two vertical pixels:
the foreground color for the top pixel, the background color for the bottom pixel.
"""

from __future__ import annotations

from PIL import Image


def render_image(
    image: Image.Image,
    max_width: int = 60,
    max_height: int = 30,
) -> str:
    """Render a Pillow Image as a string of half-block characters with ANSI colors.

    Args:
        image: The PIL Image to render.
        max_width: Maximum width in character columns.
        max_height: Maximum height in character rows (each row = 2 pixel rows).

    Returns:
        A string with ANSI escape codes that renders the image in a terminal.
    """
    img = image.convert("RGB")

    # Scale to fit within max dimensions
    # Each char column = 1 pixel wide, each char row = 2 pixels tall
    target_w = max_width
    target_h = max_height * 2  # pixel rows

    scale_w = target_w / img.width
    scale_h = target_h / img.height
    scale = min(scale_w, scale_h, 1.0)  # never upscale

    new_w = max(1, int(img.width * scale))
    new_h = max(2, int(img.height * scale))
    # Ensure even height for half-block pairing
    if new_h % 2 != 0:
        new_h += 1

    img = img.resize((new_w, new_h), Image.LANCZOS)
    pixels = img.load()

    lines: list[str] = []
    for y in range(0, new_h, 2):
        line_parts: list[str] = []
        for x in range(new_w):
            top_r, top_g, top_b = pixels[x, y]
            if y + 1 < new_h:
                bot_r, bot_g, bot_b = pixels[x, y + 1]
            else:
                bot_r, bot_g, bot_b = top_r, top_g, top_b

            # Upper half block: foreground = top pixel, background = bottom pixel
            line_parts.append(
                f"\033[38;2;{top_r};{top_g};{top_b}m"
                f"\033[48;2;{bot_r};{bot_g};{bot_b}m"
                "\u2580"
            )
        line_parts.append("\033[0m")
        lines.append("".join(line_parts))

    return "\n".join(lines)


def render_image_plain(
    image: Image.Image,
    max_width: int = 60,
    max_height: int = 30,
) -> str:
    """Render a Pillow Image as ASCII art (no color, for basic terminals).

    Uses a simple luminance-to-character mapping.
    """
    chars = " .:-=+*#%@"
    img = image.convert("L")

    scale_w = max_width / img.width
    scale_h = max_height / img.height
    scale = min(scale_w, scale_h, 1.0)

    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))

    img = img.resize((new_w, new_h), Image.LANCZOS)
    pixels = img.load()

    lines: list[str] = []
    for y in range(new_h):
        line = []
        for x in range(new_w):
            lum = pixels[x, y]
            idx = min(int(lum / 256 * len(chars)), len(chars) - 1)
            line.append(chars[idx])
        lines.append("".join(line))

    return "\n".join(lines)


def image_dimensions_text(width: int, height: int, page: int, image_id: str) -> str:
    """Format image metadata as a single-line summary."""
    return f"Page {page} | {width}x{height} | {image_id}"
