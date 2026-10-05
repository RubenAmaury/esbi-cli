"""Hostile sources for the prompt-injection tests, loaded through the real extractors.

The files in fixtures/injection/ are inert text written by us: the attacker domain is
`attacker.test` (a reserved name that never resolves), and each file asks the model for a harmless
marker (`CANARY-...`) or for something the worker must never write. Nothing here targets a real
system. The same loader feeds the tests and the real-model measurement script.
"""

from pathlib import Path

from esbi_cli.extract import ExtractedDoc
from esbi_cli.extract.clip import extract_clip
from esbi_cli.extract.html import extract_html
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.mail.convert import email_to_clip

CORPUS = Path(__file__).parent / "fixtures" / "injection"
NAMES = sorted(p.name for p in CORPUS.iterdir())
EMAILS = [n for n in NAMES if n.endswith(".eml")]


def _pdf_with(text: str) -> bytes:
    """A one-page PDF whose text layer is `text`, one line per row (plain PDF syntax, Helvetica)."""
    lines = [
        ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in text.splitlines()
    ]
    stream = "BT /F1 9 Tf 40 800 Td 12 TL\n" + "\n".join(f"({ln}) '" for ln in lines) + "\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


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
