"""Diffing tests: determinism, sections, classification."""
from lawradar.diffing.compare import classify_change, compute_diff

OLD = """The Sample Act, 2026
Section 1 — Short title and commencement
This Act may be called the Sample Act, 2026.
Section 2 — Definitions
In this Act, "fixture" means a labelled test document.
Section 3 — Compliance threshold
Every establishment shall file the quarterly return within thirty days."""

NEW = """The Sample Act, 2026
Section 1 — Short title and commencement
This Act may be called the Sample Act, 2026.
Section 2 — Definitions
In this Act, "fixture" means a labelled test document.
Section 3 — Compliance threshold
Every establishment shall file the quarterly return within forty-five days.
Section 4 — Late fee
A late fee of one hundred rupees per day shall apply."""


def test_identical_texts_no_changes():
    diff = compute_diff(OLD, OLD)
    assert diff.identical
    assert diff.changes == []
    assert diff.lines_added == diff.lines_removed == 0


def test_changed_text_detected_with_sections():
    diff = compute_diff(OLD, NEW)
    assert not diff.identical
    assert diff.lines_added >= 2 and diff.lines_removed >= 1
    assert any("Section 3" in s for s in diff.affected_sections)
    assert any("Section 4" in s for s in diff.affected_sections)
    assert diff.unified  # raw audit diff present
    assert diff.normalized_unified  # readable diff present
    locators = [c.source_locator for c in diff.changes]
    assert any("Section 3" in loc for loc in locators)


def test_diff_is_deterministic():
    first = compute_diff(OLD, NEW)
    second = compute_diff(OLD, NEW)
    assert first.unified == second.unified
    assert [c.description for c in first.changes] == [
        c.description for c in second.changes]


def test_diff_points_old_and_new_text():
    diff = compute_diff(OLD, NEW)
    joined_new = "\n".join(c.new_text for c in diff.changes)
    joined_old = "\n".join(c.old_text for c in diff.changes)
    assert "forty-five days" in joined_new
    assert "thirty days" in joined_old


def test_classify_new_document():
    assert classify_change(is_first_version=True) == "new_document"


def test_classify_unknown_without_evidence():
    diff = compute_diff(OLD, NEW)
    assert classify_change(is_first_version=False, old_extraction_ok=False,
                           new_extraction_ok=True, diff=diff) == "unknown"
    assert classify_change(is_first_version=False, old_extraction_ok=True,
                           new_extraction_ok=False, diff=diff) == "unknown"


def test_classify_text_modified_and_corrigendum():
    diff = compute_diff(OLD, NEW)
    assert classify_change(is_first_version=False, diff=diff) == "text_modified"
    corr = compute_diff(OLD, OLD + "\nCorrigendum: correction in Section 3.")
    assert corr.corrigendum_signal
    assert classify_change(is_first_version=False, diff=corr) == "corrigendum"
    amend = compute_diff(OLD, OLD + "\nAmendment inserted by Act 2 of 2026.")
    assert amend.amendment_signal
    assert classify_change(is_first_version=False,
                           diff=amend) == "possible_amendment"
