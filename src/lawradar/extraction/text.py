"""Text extraction from HTML and text-based PDFs (Milestone 2).

Rules: never silently treat an empty extraction as an empty document —
empty/suspicious results return status ``needs_review`` or ``failed`` with
warnings so the pipeline routes them for human review (M4 queue).
OCR is an optional later component: likely-scanned PDFs are flagged, not
processed.
"""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

from lawradar.ingestion.hashing import normalize_text

# Below this many extracted characters a PDF is treated as likely-scanned.
SCANNED_PDF_MIN_CHARS = 100
# Below this many characters any extraction is suspiciously short.
MIN_TEXT_CHARS = 20


@dataclass
class ExtractionResult:
    text: str
    normalized: str
    method: str
    status: str  # ok | needs_review | failed
    warnings: list[str] = field(default_factory=list)
    pages: int = 1


class _HtmlStripper(HTMLParser):
    """Lenient HTML → text. Script/style content is dropped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "title"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        lines = "".join(self._parts).splitlines()
        cleaned = [" ".join(line.split()) for line in lines]
        return "\n".join(line for line in cleaned if line)


def extract_html(raw: bytes) -> ExtractionResult:
    warnings: list[str] = []
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("utf-8", errors="replace")
        warnings.append("html decoded with replacement characters (not pure UTF-8)")
    if "\ufffd" in html and not warnings:
        warnings.append("html contains replacement characters")
    stripper = _HtmlStripper()
    try:
        stripper.feed(html)
    except Exception as exc:  # noqa: BLE001 — HTMLParser is lenient; be safe anyway
        return ExtractionResult(
            text="",
            normalized="",
            method="html",
            status="failed",
            warnings=warnings + [f"malformed HTML could not be parsed: {exc}"],
        )
    text = stripper.get_text()
    if not text.strip():
        return ExtractionResult(
            text="", normalized="", method="html", status="needs_review",
            warnings=warnings + ["empty extraction: no readable text in HTML"],
        )
    if len(text.strip()) < MIN_TEXT_CHARS:
        warnings.append("suspiciously short extraction; flagged for review")
        return ExtractionResult(
            text=text, normalized=normalize_text(text), method="html",
            status="needs_review", warnings=warnings,
        )
    return ExtractionResult(
        text=text, normalized=normalize_text(text), method="html",
        status="ok", warnings=warnings,
    )


def extract_txt(raw: bytes) -> ExtractionResult:
    warnings: list[str] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        warnings.append("text decoded with replacement characters (not pure UTF-8)")
    if "\ufffd" in text and not warnings:
        warnings.append("text contains replacement characters")
    if not text.strip():
        return ExtractionResult(
            text="", normalized="", method="text", status="needs_review",
            warnings=warnings + ["empty extraction: no readable text"],
        )
    if len(text.strip()) < MIN_TEXT_CHARS:
        warnings.append("suspiciously short extraction; flagged for review")
        return ExtractionResult(
            text=text, normalized=normalize_text(text), method="text",
            status="needs_review", warnings=warnings,
        )
    return ExtractionResult(
        text=text, normalized=normalize_text(text), method="text",
        status="ok", warnings=warnings,
    )


def extract_pdf(raw: bytes) -> ExtractionResult:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader  # local import: clearer error when missing
    except ImportError:
        return ExtractionResult(
            text="", normalized="", method="pdf", status="failed",
            warnings=["pypdf is not installed; cannot extract PDF text"],
        )
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 — corrupt/encrypted PDFs land here
        return ExtractionResult(
            text="", normalized="", method="pdf", status="failed",
            warnings=[f"PDF could not be opened: {exc}"],
        )
    if getattr(reader, "is_encrypted", False):
        return ExtractionResult(
            text="", normalized="", method="pdf", status="failed",
            warnings=["encrypted PDF; text extraction refused"],
        )
    pages_text: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"page {i} extraction failed: {exc}")
            page_text = ""
        page_text = unicodedata.normalize("NFKC", page_text).strip()
        pages_text.append(f"[page {i}]\n{page_text}" if page_text else f"[page {i}]\n")
    text = "\n\n".join(pages_text).strip()
    chars = len(text.replace("[page", "").strip())
    if chars < SCANNED_PDF_MIN_CHARS:
        warnings.append(
            "likely scanned PDF (too little extractable text); "
            "OCR required — flagged for review, not silently accepted"
        )
        return ExtractionResult(
            text=text, normalized=normalize_text(text), method="pdf",
            status="needs_review", warnings=warnings, pages=len(reader.pages),
        )
    return ExtractionResult(
        text=text, normalized=normalize_text(text), method="pdf",
        status="ok", warnings=warnings, pages=len(reader.pages),
    )


def extract_text(
    raw: bytes, content_type: str = "", filename: str = ""
) -> ExtractionResult:
    """Dispatch extraction by content type (with filename fallback)."""
    ctype = (content_type or "").lower().split(";")[0].strip()
    name = (filename or "").lower()
    if ctype in ("text/html", "application/xhtml+xml") or name.endswith(
        (".html", ".htm")
    ):
        return extract_html(raw)
    if ctype == "application/pdf" or name.endswith(".pdf"):
        return extract_pdf(raw)
    if ctype in ("text/plain", "") or name.endswith(".txt"):
        return extract_txt(raw)
    return ExtractionResult(
        text="", normalized="",
        method="unknown", status="failed",
        warnings=[f"unexpected content type {content_type!r}; flagged for review"],
    )
