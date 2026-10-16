"""Fixture adapter: explicitly labelled demo data (never real legal data).

Powers ``lawradar ingest fixture-sample`` and the test suite so the whole
pipeline is demonstrable without network access. Every fixture title and
report carries a ``[FIXTURE]`` marker; fixture output must never be
presented as a real legal finding.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SOURCE_ID = "fixture-sample"


@dataclass
class FixtureDocument:
    source_document_id: str
    title: str
    filename: str
    document_type: str
    issuing_authority: str
    jurisdiction: str
    official_url: str

    def read(self) -> bytes:
        path = FIXTURE_DIR / self.filename
        return path.read_bytes()


def list_fixtures() -> list[FixtureDocument]:
    return [
        FixtureDocument(
            source_document_id="sample-act-v1",
            title="[FIXTURE] Sample Act 2026 — base text",
            filename="sample_act_v1.html",
            document_type="Act",
            issuing_authority="Fixture Authority",
            jurisdiction="central",
            official_url="https://example.invalid/fixture/sample-act-v1",
        ),
        FixtureDocument(
            source_document_id="sample-act-v2",
            title="[FIXTURE] Sample Act 2026 — amended text",
            filename="sample_act_v2.html",
            document_type="Act",
            issuing_authority="Fixture Authority",
            jurisdiction="central",
            official_url="https://example.invalid/fixture/sample-act-v2",
        ),
    ]
