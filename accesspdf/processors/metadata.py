"""MetadataProcessor — sets document language, title, and MarkInfo."""

from __future__ import annotations

import logging
from pathlib import Path

import pikepdf

from accesspdf.models import ProcessorResult
from accesspdf.pipeline import register_processor
from accesspdf.processors._pdf_helpers import ensure_mark_info

logger = logging.getLogger(__name__)

# langdetect ISO 639-1 → BCP 47 mapping for common languages
_LANG_MAP: dict[str, str] = {
    "en": "en-US",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "it": "it-IT",
    "pt": "pt-BR",
    "nl": "nl-NL",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
}


@register_processor
class MetadataProcessor:
    @property
    def name(self) -> str:
        return "Metadata"

    def process(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        try:
            return self._fix_metadata(pdf)
        except Exception as exc:
            logger.error("MetadataProcessor failed: %s", exc, exc_info=True)
            return ProcessorResult(
                processor_name=self.name, success=False, error=str(exc)
            )

    def _fix_metadata(self, pdf: pikepdf.Pdf) -> ProcessorResult:
        changes = 0
        warnings: list[str] = []

        # 1. Set language
        if "/Lang" not in pdf.Root:
            lang = self._detect_language(pdf)
            pdf.Root["/Lang"] = lang
            changes += 1

        # 2. Set title
        if not self._has_title(pdf):
            title = self._derive_title(pdf)
            if title:
                with pdf.open_metadata() as meta:
                    meta["dc:title"] = title
                changes += 1

        # 3. Ensure MarkInfo
        mark_info = ensure_mark_info(pdf)
        if not mark_info.get("/Marked"):
            changes += 1

        # 4. Set display title
        if "/ViewerPreferences" not in pdf.Root:
            pdf.Root["/ViewerPreferences"] = pikepdf.Dictionary()
        vp = pdf.Root["/ViewerPreferences"]
        if "/DisplayDocTitle" not in vp or not bool(vp["/DisplayDocTitle"]):
            vp["/DisplayDocTitle"] = True
            changes += 1

        return ProcessorResult(
            processor_name=self.name,
            changes_made=changes,
            warnings=warnings,
        )

    def _detect_language(self, pdf: pikepdf.Pdf) -> str:
        """Detect document language using langdetect."""
        try:
            from accesspdf.processors._text_extract import extract_full_text

            # We need the file path — extract from the pdf object
            # Use a temporary approach: extract text from content streams directly
            text = ""
            for page in pdf.pages:
                if "/Contents" not in page:
                    continue
                try:
                    ops = pikepdf.parse_content_stream(page)
                    for operands, operator in ops:
                        if operator == pikepdf.Operator("Tj") and operands:
                            text += str(operands[0]) + " "
                        elif operator == pikepdf.Operator("TJ") and operands:
                            for item in operands[0]:
                                if isinstance(item, (pikepdf.String, str)):
                                    text += str(item) + " "
                except Exception:
                    pass

            if len(text.strip()) < 20:
                return "en-US"

            from langdetect import detect, LangDetectException
            try:
                lang_code = detect(text[:5000])
                return _LANG_MAP.get(lang_code, lang_code)
            except LangDetectException:
                return "en-US"

        except Exception:
            logger.debug("Language detection failed, defaulting to en-US", exc_info=True)
            return "en-US"

    def _has_title(self, pdf: pikepdf.Pdf) -> bool:
        """Check if the PDF already has a title set."""
        if pdf.docinfo and "/Title" in pdf.docinfo:
            title = str(pdf.docinfo["/Title"]).strip()
            if title:
                return True
        return False

    def _derive_title(self, pdf: pikepdf.Pdf) -> str:
        """Try to derive a title from the first text in the document."""
        try:
            for page in pdf.pages:
                if "/Contents" not in page:
                    continue
                ops = pikepdf.parse_content_stream(page)
                for operands, operator in ops:
                    if operator == pikepdf.Operator("Tj") and operands:
                        text = str(operands[0]).strip()
                        if len(text) > 2:
                            return text[:200]
                    elif operator == pikepdf.Operator("TJ") and operands:
                        parts = []
                        for item in operands[0]:
                            if isinstance(item, (pikepdf.String, str)):
                                parts.append(str(item))
                        text = "".join(parts).strip()
                        if len(text) > 2:
                            return text[:200]
        except Exception:
            pass
        return "Untitled Document"
