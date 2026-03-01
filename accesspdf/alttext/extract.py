"""Extract images from PDFs as Pillow Image objects."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import pikepdf
from PIL import Image

logger = logging.getLogger(__name__)


def extract_image(pdf_path: Path, image_hash: str) -> Image.Image | None:
    """Extract a specific image from a PDF by its md5 hash.

    Returns a Pillow Image or None if not found.
    """
    with pikepdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            result = _search_page(page, image_hash)
            if result is not None:
                return result
    return None


def extract_all_images(pdf_path: Path) -> list[tuple[str, int, Image.Image]]:
    """Extract all images from a PDF.

    Returns a list of (hash, page_number, Image) tuples.
    Deduplicates by hash.
    """
    results: list[tuple[str, int, Image.Image]] = []
    seen: set[str] = set()

    with pikepdf.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            _collect_page_images(page, page_idx, seen, results)

    return results


def _search_page(page: pikepdf.Page, target_hash: str) -> Image.Image | None:
    """Search a page for an image with a specific hash."""
    if "/Resources" not in page or "/XObject" not in page["/Resources"]:
        return None

    for _name, xobj_ref in page["/Resources"]["/XObject"].items():
        try:
            xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
            if not isinstance(xobj, pikepdf.Stream):
                continue

            subtype = str(xobj.get("/Subtype", ""))
            if subtype == "/Image":
                result = _try_extract(xobj, target_hash)
                if result is not None:
                    return result
            elif subtype == "/Form":
                result = _search_form(xobj, target_hash)
                if result is not None:
                    return result
        except Exception:
            logger.debug("Error searching XObject", exc_info=True)

    return None


def _search_form(form_xobj: pikepdf.Stream, target_hash: str) -> Image.Image | None:
    """Search inside a Form XObject for an image with a specific hash."""
    try:
        resources = form_xobj.get("/Resources")
        if resources is None or "/XObject" not in resources:
            return None
        for _name, inner_ref in resources["/XObject"].items():
            inner = inner_ref.resolve() if hasattr(inner_ref, "resolve") else inner_ref
            if not isinstance(inner, pikepdf.Stream):
                continue
            if str(inner.get("/Subtype", "")) == "/Image":
                result = _try_extract(inner, target_hash)
                if result is not None:
                    return result
    except Exception:
        logger.debug("Error searching form XObject", exc_info=True)
    return None


def _try_extract(xobj: pikepdf.Stream, target_hash: str) -> Image.Image | None:
    """Check if an XObject matches the target hash and extract as Image."""
    raw = bytes(xobj.read_raw_bytes())
    img_hash = hashlib.md5(raw).hexdigest()
    if img_hash != target_hash:
        return None
    return _xobj_to_pil(xobj)


def _collect_page_images(
    page: pikepdf.Page,
    page_num: int,
    seen: set[str],
    results: list[tuple[str, int, Image.Image]],
) -> None:
    """Collect all images from a page."""
    if "/Resources" not in page or "/XObject" not in page["/Resources"]:
        return

    for _name, xobj_ref in page["/Resources"]["/XObject"].items():
        try:
            xobj = xobj_ref.resolve() if hasattr(xobj_ref, "resolve") else xobj_ref
            if not isinstance(xobj, pikepdf.Stream):
                continue

            subtype = str(xobj.get("/Subtype", ""))
            if subtype == "/Image":
                _try_collect(xobj, page_num, seen, results)
            elif subtype == "/Form":
                _collect_form_images(xobj, page_num, seen, results)
        except Exception:
            logger.debug("Error collecting image on page %d", page_num, exc_info=True)


def _collect_form_images(
    form_xobj: pikepdf.Stream,
    page_num: int,
    seen: set[str],
    results: list[tuple[str, int, Image.Image]],
) -> None:
    """Collect images from inside a Form XObject."""
    try:
        resources = form_xobj.get("/Resources")
        if resources is None or "/XObject" not in resources:
            return
        for _name, inner_ref in resources["/XObject"].items():
            inner = inner_ref.resolve() if hasattr(inner_ref, "resolve") else inner_ref
            if not isinstance(inner, pikepdf.Stream):
                continue
            if str(inner.get("/Subtype", "")) == "/Image":
                _try_collect(inner, page_num, seen, results)
    except Exception:
        logger.debug("Error collecting form images", exc_info=True)


def _try_collect(
    xobj: pikepdf.Stream,
    page_num: int,
    seen: set[str],
    results: list[tuple[str, int, Image.Image]],
) -> None:
    """Try to extract an image XObject and add it to results."""
    raw = bytes(xobj.read_raw_bytes())
    img_hash = hashlib.md5(raw).hexdigest()
    if img_hash in seen:
        return
    seen.add(img_hash)

    img = _xobj_to_pil(xobj)
    if img is not None:
        results.append((img_hash, page_num, img))


def _xobj_to_pil(xobj: pikepdf.Stream) -> Image.Image | None:
    """Convert a pikepdf image XObject to a Pillow Image.

    Always returns an RGB or L (grayscale) image so callers can safely
    save as PNG without mode errors (e.g. CMYK → RGB).
    """
    try:
        pdfimage = pikepdf.PdfImage(xobj)
        img = pdfimage.as_pil_image()
        return _ensure_rgb(img)
    except Exception:
        logger.debug("pikepdf.PdfImage extraction failed, trying raw decode", exc_info=True)

    # Fallback for images with SMask (transparency) or exotic colorspaces
    # like CalRGB: strip the SMask and try again
    if "/SMask" in xobj:
        try:
            saved_smask = xobj["/SMask"]
            del xobj["/SMask"]
            pdfimage = pikepdf.PdfImage(xobj)
            img = pdfimage.as_pil_image()
            xobj["/SMask"] = saved_smask  # restore
            return _ensure_rgb(img)
        except Exception:
            logger.debug("SMask-stripped extraction also failed", exc_info=True)

    # Fallback: try to decode decompressed bytes
    try:
        raw = bytes(xobj.read_bytes())
        w = int(xobj.get("/Width", 0))
        h = int(xobj.get("/Height", 0))
        bpc = int(xobj.get("/BitsPerComponent", 8))
        cs = str(xobj.get("/ColorSpace", ""))

        if w == 0 or h == 0:
            return None

        if "/DeviceRGB" in cs or "/RGB" in cs:
            mode = "RGB"
        elif "/DeviceGray" in cs or "/Gray" in cs:
            mode = "L"
        else:
            mode = "RGB"

        expected_size = w * h * (3 if mode == "RGB" else 1) * (bpc // 8)
        if len(raw) >= expected_size:
            img = Image.frombytes(mode, (w, h), raw[:expected_size])
            return _ensure_rgb(img)
    except Exception:
        logger.debug("Raw image decode failed", exc_info=True)

    return None


def prepare_for_ai(img: Image.Image, *, max_dim: int = 512) -> bytes:
    """Resize a PIL image and return PNG bytes ready for an AI provider.

    Vision models don't need full-resolution PDF images.  Downsizing to
    *max_dim* pixels on the longest side dramatically reduces payload size
    and inference time while preserving enough detail for alt-text generation.
    """
    # Resize if larger than max_dim on either axis
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.debug("Resized image from %dx%d to %dx%d for AI", w, h, new_w, new_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ensure_rgb(img: Image.Image) -> Image.Image:
    """Convert any image mode (CMYK, P, LA, etc.) to RGB for safe PNG export."""
    if img.mode in ("RGB", "L"):
        return img
    if img.mode == "CMYK":
        return img.convert("RGB")
    if img.mode in ("RGBA", "LA", "PA"):
        # Keep alpha by converting to RGBA, which PNG supports
        return img.convert("RGBA")
    # Catch-all for any other mode (P, I, F, etc.)
    return img.convert("RGB")
