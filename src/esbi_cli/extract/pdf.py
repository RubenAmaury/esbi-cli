import pypdfium2 as pdfium

from esbi_cli.extract import ExtractedDoc, ExtractError
from esbi_cli.extract.image import MAX_SIDE_PX, MIN_CHARS, NO_OCR, read_text
from esbi_cli.extract.pdf_figures import locate_figures, page_images, render_figures, render_png
from esbi_cli.extract.pdf_text import document_lines, pdf_to_markdown

OCR_DPI = 130  # a scanned page at this resolution reads as well as at twice the size


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
        meta_title = doc.get_metadata_dict().get("Title", "") or ""
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
    title = meta_title.strip() or fallback_title.replace("-", " ").replace("_", " ").strip()
    return ExtractedDoc(
        title=title,
        text=text.strip(),
        kind="paper",
        pdf_bytes=data,
        figures=figures,
        warnings=warnings,
    )
