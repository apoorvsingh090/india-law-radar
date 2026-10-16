"""Manual-import adapter: ingest a locally held file with recorded provenance.

Use when automated access to an official source is not yet verified or not
permitted. The operator downloads (or receives) the document through
permitted means; this adapter records the file hash, original filename,
declared official URL, and import time — never inventing provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_MANUAL_BYTES = 50_000_000

_SUFFIX_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
}


@dataclass
class ManualFile:
    path: Path
    data: bytes
    content_type: str
    warnings: list[str]


def read_manual_file(path: str | Path) -> ManualFile:
    """Read + validate a manual-import file. Raises on policy violations."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"manual import file not found: {path}")
    size = resolved.stat().st_size
    if size == 0:
        raise ValueError(f"manual import file is empty: {path}")
    if size > MAX_MANUAL_BYTES:
        raise ValueError(
            f"manual import file too large: {size} bytes (limit {MAX_MANUAL_BYTES})"
        )
    data = resolved.read_bytes()
    suffix = resolved.suffix.lower()
    content_type = _SUFFIX_TYPES.get(suffix, "application/octet-stream")
    warnings: list[str] = []
    if content_type == "application/octet-stream":
        warnings.append(
            f"unrecognised suffix {suffix!r}; stored as bytes, "
            "extraction will flag it for review"
        )
    return ManualFile(path=resolved, data=data, content_type=content_type,
                      warnings=warnings)
