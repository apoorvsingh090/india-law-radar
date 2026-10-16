"""Hashing tests: stability, sensitivity, normalisation."""
from lawradar.ingestion.hashing import normalize_text, sha256_bytes, sha256_file


def test_sha256_stable_and_known_vector():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")


def test_sha256_sensitive_to_single_byte():
    assert sha256_bytes(b"thirty days") != sha256_bytes(b"forty-five days")


def test_sha256_file_matches_bytes(tmp_path):
    target = tmp_path / "doc.bin"
    target.write_bytes(b"hello law radar")
    assert sha256_file(target) == sha256_bytes(b"hello law radar")


def test_normalize_collapses_whitespace():
    assert normalize_text("  Section   3\n\nfile  within\t30 days ") == (
        "Section 3 file within 30 days"
    )
