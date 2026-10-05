"""The PDFs the tests read. They are committed files (tests/fixtures/pdf/), written once with a
throwaway script, so no PDF library is needed to build them and the extractor is tested on files
that it did not make."""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


def pdf_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
