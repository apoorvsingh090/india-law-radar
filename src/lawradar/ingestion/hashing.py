"""Hashing and normalisation helpers (deterministic, stdlib only)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_WS_RE = re.compile(r"\s+")


def sha256_bytes(data: bytes) -> str:
    """Stable SHA-256 hex digest over raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """SHA-256 over a file without loading it fully into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    """Normalise text for comparison: NFKC + collapsed whitespace.

    The original text is always preserved separately; this form is only
    used for deterministic comparison and readable diffs (M3).
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _WS_RE.sub(" ", normalized).strip()
    return normalized
