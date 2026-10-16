"""Extraction tests: HTML, text, PDF, and review flagging."""
from pathlib import Path

from lawradar.extraction.text import extract_text


def _fixture(name: str) -> bytes:
    base = Path("src/lawradar/sources/fixtures") / name
    if not base.is_file():  # installed-package fallback
        import lawradar.sources.fixture as fix

        base = Path(fix.FIXTURE_DIR) / name
    return base.read_bytes()


def test_html_fixture_extracts_expected_text():
    result = extract_text(_fixture("sample_act_v1.html"), "text/html")
    assert result.status == "ok"
    assert "thirty days" in result.text
    assert "Sample Act" in result.text
    assert "<h2>" not in result.text  # tags stripped


def test_html_empty_flagged_for_review():
    raw = b"<html><head></head><body><script>var x = 1;</script></body></html>"
    result = extract_text(raw, "text/html")
    assert result.status == "needs_review"
    assert any("empty" in w for w in result.warnings)


def test_text_ok_and_empty():
    ok = extract_text(b"This is a sufficiently long plain text fixture document here.",
                      "text/plain")
    assert ok.status == "ok"
    empty = extract_text(b"   \n  ", "text/plain")
    assert empty.status == "needs_review"


def test_unknown_type_failed():
    result = extract_text(b"\x00\x01\x02", "application/octet-stream",
                          filename="blob.bin")
    assert result.status == "failed"
    assert result.warnings


def _make_text_pdf(text: str) -> bytes:
    """Build a minimal valid single-page PDF with extractable text."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF").encode()
    return pdf


def test_pdf_text_based_ok():
    sentence = ("Section 3. Every establishment shall file the quarterly return "
                "within thirty days of the end of the quarter. ")
    result = extract_text(_make_text_pdf(sentence), "application/pdf",
                          filename="act.pdf")
    assert result.status == "ok", result.warnings
    assert "thirty days" in result.text
    assert result.pages == 1


def test_pdf_scanned_flagged():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    import io

    buf = io.BytesIO()
    writer.write(buf)
    result = extract_text(buf.getvalue(), "application/pdf")
    assert result.status == "needs_review"
    assert any("scanned" in w for w in result.warnings)
