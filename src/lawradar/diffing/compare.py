"""Deterministic text comparison (Milestone 3).

Produces both a raw line-based diff (auditability) and a normalised diff
(readable reports), per spec section 7. Never uses an LLM: two documents
differ if and only if their bytes/texts differ. Section attribution maps
changed lines to the nearest preceding legal heading.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from lawradar.ingestion.hashing import normalize_text

# Headings that delimit addressable legal provisions.
_HEADING_RE = re.compile(
    r"^\s*(Section|Article|Rule|Regulation|Chapter|Part|Schedule|Clause|"
    r"Order|Paragraph|Sub-section|Subsection)\s+([\w\d\(\)\-\.\/]+)",
    re.IGNORECASE,
)
_AMEND_RE = re.compile(r"\bamend\w*\b|\bsubstitut\w+\b|\binsert\w*\b|\bomiss?ion\b",
                       re.IGNORECASE)
_CORRIGENDUM_RE = re.compile(
    r"\bcorrigendum\b|\bcorrection\b|\brectif\w+\b|\berrat\w*\b", re.IGNORECASE)

# Snippet cap per change so reports stay readable; full text stays on disk.
SNIPPET_CHARS = 2000


@dataclass
class TextChange:
    description: str
    old_text: str
    new_text: str
    source_locator: str  # nearest section heading or line reference
    confidence: str  # high | medium | low


@dataclass
class DiffResult:
    identical: bool
    unified: str  # raw line diff (audit)
    normalized_unified: str  # normalised-text diff (readable)
    lines_added: int
    lines_removed: int
    changes: list[TextChange] = field(default_factory=list)
    affected_sections: list[str] = field(default_factory=list)
    amendment_signal: bool = False
    corrigendum_signal: bool = False


def _headings(lines: list[str]) -> dict[int, str]:
    """Map 0-based line index -> heading text for heading lines."""
    found: dict[int, str] = {}
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line.strip())
        if match:
            found[i] = " ".join(line.strip().split())
    return found


def _nearest_heading(heads: dict[int, str], line_no: int) -> str:
    best = ""
    for idx in sorted(heads):
        if idx <= line_no:
            best = heads[idx]
        else:
            break
    return best or f"line {line_no + 1}"


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > SNIPPET_CHARS:
        return text[:SNIPPET_CHARS] + " …[truncated]"
    return text


def compute_diff(old_text: str, new_text: str) -> DiffResult:
    """Deterministic line diff between two extracted texts."""
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    unified = "".join(
        difflib.unified_diff(old_lines, new_lines, "old", "new", lineterm="\n")
    )
    old_norm = normalize_text(old_text or "").split(" ")
    new_norm = normalize_text(new_text or "").split(" ")
    normalized_unified = "".join(
        difflib.unified_diff(old_norm, new_norm, "old", "new", lineterm="\n")
    )
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    new_heads = _headings(new_lines)
    old_heads = _headings(old_lines)
    changes: list[TextChange] = []
    sections: list[str] = []
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed += max(0, i2 - i1)
        added += max(0, j2 - j1)
        old_chunk = "\n".join(old_lines[i1:i2])
        new_chunk = "\n".join(new_lines[j1:j2])
        locator = _nearest_heading(new_heads, j1) if new_chunk else _nearest_heading(
            old_heads, i1
        )
        if locator not in sections and not locator.startswith("line "):
            sections.append(locator)
        # Headings introduced (or removed) inside the changed chunk itself
        # also count as affected — e.g. a newly inserted "Section 4".
        for idx in range(j1, j2):
            if idx in new_heads and new_heads[idx] not in sections:
                sections.append(new_heads[idx])
        for idx in range(i1, i2):
            if idx in old_heads and old_heads[idx] not in sections:
                sections.append(old_heads[idx])
        if tag == "insert":
            description = f"Inserted text at {locator}"
        elif tag == "delete":
            description = f"Removed text at {locator}"
        else:
            description = f"Reworded text at {locator}"
        contiguous = (i2 - i1) + (j2 - j1) <= 6
        changes.append(
            TextChange(
                description=description,
                old_text=_clip(old_chunk),
                new_text=_clip(new_chunk),
                source_locator=locator,
                confidence="high" if contiguous else "medium",
            )
        )
    identical = not changes
    added_chunks: list[str] = []
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added_chunks.extend(new_lines[j1:j2])
    added_text = "\n".join(added_chunks)
    return DiffResult(
        identical=identical,
        unified=unified,
        normalized_unified=normalized_unified,
        lines_added=added,
        lines_removed=removed,
        changes=changes,
        affected_sections=sections,
        amendment_signal=bool(_AMEND_RE.search(added_text)),
        corrigendum_signal=bool(_CORRIGENDUM_RE.search(added_text)),
    )


def classify_change(
    *,
    is_first_version: bool,
    old_extraction_ok: bool = True,
    new_extraction_ok: bool = True,
    diff: DiffResult | None = None,
) -> str:
    """Deterministic change-type label (spec section 5.4).

    Never infers what the evidence does not support: unreadable evidence
    yields ``unknown``.
    """
    if is_first_version:
        return "new_document"
    if not (old_extraction_ok and new_extraction_ok):
        return "unknown"
    if diff is None or diff.identical:
        return "metadata_modified"
    if diff.corrigendum_signal:
        return "corrigendum"
    if diff.amendment_signal:
        return "possible_amendment"
    return "text_modified"
