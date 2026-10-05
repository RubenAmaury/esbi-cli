"""Hostile sources for the prompt-injection tests, loaded through the real extractors.

The files in fixtures/injection/ are inert text written by us: the attacker domain is
`attacker.test` (a reserved name that never resolves), and each file asks the model for a harmless
marker (`CANARY-...`) or for something the worker must never write. Nothing here targets a real
system. The same loader feeds the tests and the real-model measurement script.
"""

from pathlib import Path

import pymupdf

from esbi_cli.extract import ExtractedDoc
from esbi_cli.extract.clip import extract_clip
from esbi_cli.extract.html import extract_html
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.mail.convert import email_to_clip

CORPUS = Path(__file__).parent / "fixtures" / "injection"
NAMES = sorted(p.name for p in CORPUS.iterdir())
EMAILS = [n for n in NAMES if n.endswith(".eml")]


def _pdf_with(text: str) -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), text, fontsize=9)
    return pdf.tobytes()


def load(name: str, scratch: Path) -> ExtractedDoc:
    """The document the worker would get for this file. `scratch` holds the clip an email becomes."""
    path = CORPUS / name
    if path.suffix == ".html":
        return extract_html(path.read_text(encoding="utf-8"), url="https://attacker.test/post")
    if path.suffix == ".txt":  # the text of a PDF: build a real one and extract it
        return extract_pdf_bytes(_pdf_with(path.read_text(encoding="utf-8")), "paper")
    if path.suffix == ".eml":  # like `sb fetch`: the mail becomes a clip note in the inbox
        clip = email_to_clip(path.read_bytes(), "en")
        scratch.mkdir(parents=True, exist_ok=True)
        saved = scratch / clip.filename
        saved.write_text(clip.content, encoding="utf-8")
        return extract_clip(saved)
    return extract_clip(path)
