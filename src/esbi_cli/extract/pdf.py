import re
import unicodedata

import pypdfium2 as pdfium

from esbi_cli.extract import ExtractedDoc, ExtractError
from esbi_cli.extract.image import MAX_SIDE_PX, MIN_CHARS, NO_OCR, read_text
from esbi_cli.extract.pdf_figures import locate_figures, page_images, render_figures, render_png
from esbi_cli.extract.pdf_text import document_lines, pdf_to_markdown

OCR_DPI = 130  # a scanned page at this resolution reads as well as at twice the size
TITLE_PAGES = 2  # a real title is on the cover; a template's leftover Title is on none of them


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def _shown_title(doc: pdfium.PdfDocument, meta_title: str) -> str:
    """The metadata Title when the first pages show it, else "": decks made from one template
    keep its old Title (16 course decks were all "Machine Learning Landscape & Python Basics")."""
    wanted = _words(meta_title)
    if not wanted:
        return ""
    pages = range(min(TITLE_PAGES, len(doc)))
    shown = _words(" ".join(doc[i].get_textpage().get_text_range() for i in pages))
    return meta_title.strip() if wanted in shown else ""


def _file_title(stem: str) -> str:
    """A slug (no spaces) splits on - and _; a name with spaces keeps its hyphens. A deck exported
    as `name.pptx.pdf` loses the `.pptx`."""
    stem = re.sub(r"\.(pptx?|docx?|key|odp)$", "", stem, flags=re.IGNORECASE)
    if " " not in stem:
        stem = stem.replace("-", " ")
    return " ".join(stem.replace("_", " ").split())


def _ocr_pages(doc: pdfium.PdfDocument, ocr, max_pages: int) -> tuple[str, list[str]]:
    """A scanned PDF has no text layer: render its first `max_pages` pages and read them."""
    pages = []
    for number in range(1, min(len(doc), max_pages) + 1):
        png = render_png(doc[number - 1], None, OCR_DPI, MAX_SIDE_PX)
        pages.append(read_text(ocr, png, f"page {number}").strip())
    text = "\n\n".join(p for p in pages if p)
    if len(text) < MIN_CHARS:
        raise ExtractError("PDF has no readable text, even with OCR")
    if len(doc) <= max_pages:
        return text, []
    return text, [f"OCR read the first {max_pages} of {len(doc)} pages ([run].ocr_max_pages)"]


def extract_pdf_bytes(
    data: bytes, fallback_title: str, ocr=None, max_ocr_pages: int = 10
) -> ExtractedDoc:
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:  # a broken file, or one that needs a password
        raise ExtractError(f"Could not open PDF: {exc}") from exc
    try:
        pages = document_lines(doc)
        images = {index: page_images(doc[index]) for index in range(len(doc))}
        candidates, drawings = locate_figures(doc, pages, images)
        text = pdf_to_markdown(doc, pages, images, drawings)
        meta_title = _shown_title(doc, doc.get_metadata_dict().get("Title", "") or "")
        warnings: list[str] = []
        if len(text.strip()) < 200:
            if ocr is None:
                raise ExtractError(f"PDF has almost no extractable text (scanned?): {NO_OCR}")
            text, warnings = _ocr_pages(doc, ocr, max_ocr_pages)
            figures = []  # the pages are images: showing them all as figures would only add noise
        else:
            figures = render_figures(doc, candidates)
    except ExtractError:
        raise
    except Exception as exc:  # PDFium and its binding raise several unrelated error types
        raise ExtractError(f"Could not read PDF: {exc}") from exc
    finally:
        doc.close()
    title = meta_title or _file_title(fallback_title)
    return ExtractedDoc(
        title=title,
        text=text.strip(),
        kind="paper",
        pdf_bytes=data,
        figures=figures,
        warnings=warnings,
    )
