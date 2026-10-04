import hashlib
import re

import pymupdf
import pymupdf4llm

from esbi_cli.extract import ExtractedDoc, ExtractError, Figure
from esbi_cli.extract.image import MAX_SIDE_PX, MIN_CHARS, NO_OCR, read_text

CAPTION = re.compile(r"\s*(figure|fig\.?|figura)\s*\d+", re.I)
MAX_FIGURES = 8
MIN_WIDTH_POINTS, MIN_HEIGHT_POINTS = (
    100,
    80,
)  # PDF points: smaller images are icons, logos, bullets
MAX_ASPECT = 6  # thinner strips are rules and banners, not figures


def _caption_for(captions: list, rect: pymupdf.Rect) -> str | None:
    """The figure caption printed just below the image (or just above it)."""
    below = [b for b in captions if rect.y1 - 5 <= b[1] < rect.y1 + 90]
    above = [b for b in captions if 0 <= rect.y0 - b[3] < 60]
    nearest = sorted(below, key=lambda b: b[1] - rect.y1) or above
    return " ".join(nearest[0][4].split())[:200] if nearest else None


MAX_FIGURE_PX = 3000


def _dpi_for(width_points: float, height_points: float) -> int:
    """150 dpi, lowered so that no side passes MAX_FIGURE_PX: a hostile PDF can claim a huge image."""
    return max(
        1, int(min(150, MAX_FIGURE_PX * 72 / max(width_points, height_points, 1)))
    )  # pymupdf wants an int


def _figures(doc: pymupdf.Document) -> list[Figure]:
    """Up to MAX_FIGURES real figures: the captioned ones first, then the biggest."""
    candidates = []  # (page number, rect, caption)
    for number, page in enumerate(doc, 1):
        captions = [b for b in page.get_text("blocks") if len(b) > 4 and CAPTION.match(b[4])]
        for image in page.get_images(full=True):
            for rect in page.get_image_rects(image[0]):
                w, h = rect.width, rect.height
                if w < MIN_WIDTH_POINTS or h < MIN_HEIGHT_POINTS or max(w / h, h / w) > MAX_ASPECT:
                    continue
                candidates.append((number, rect, _caption_for(captions, rect)))
    candidates.sort(key=lambda c: (c[2] is None, -c[1].get_area()))
    figures, seen = [], set()
    for number, rect, caption in candidates:
        if len(figures) == MAX_FIGURES:
            break
        # rendering the image's area (not extracting the raw stream) keeps masks and overlays right
        data = (
            doc[number - 1]
            .get_pixmap(clip=rect, dpi=_dpi_for(rect.width, rect.height))
            .tobytes("png")
        )
        digest = hashlib.sha1(data).hexdigest()
        if digest not in seen:
            seen.add(digest)
            figures.append(Figure(data=data, page=number, caption=caption))
    return sorted(figures, key=lambda f: f.page)  # reading order


def _ocr_pages(doc: pymupdf.Document, ocr, max_pages: int) -> tuple[str, list[str]]:
    """A scanned PDF has no text layer: render its first `max_pages` pages and read them."""
    pages = []
    for number, page in enumerate(doc, 1):
        if number > max_pages:
            break
        dpi = max(1, int(min(130, MAX_SIDE_PX * 72 / max(page.rect.width, page.rect.height, 1))))
        png = page.get_pixmap(dpi=dpi).tobytes("png")
        pages.append(read_text(ocr, png, f"page {number}").strip())
    text = "\n\n".join(p for p in pages if p)
    if len(text) < MIN_CHARS:
        raise ExtractError("PDF has no readable text, even with OCR")
    if doc.page_count <= max_pages:
        return text, []
    return text, [f"OCR read the first {max_pages} of {doc.page_count} pages ([run].ocr_max_pages)"]


def extract_pdf_bytes(
    data: bytes, fallback_title: str, ocr=None, max_ocr_pages: int = 10
) -> ExtractedDoc:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf raises several unrelated error types
        raise ExtractError(f"Could not open PDF: {exc}") from exc
    with doc:
        text = pymupdf4llm.to_markdown(doc)
        meta_title = (doc.metadata or {}).get("title", "") or ""
        warnings: list[str] = []
        if len(text.strip()) < 200:
            if ocr is None:
                raise ExtractError(f"PDF has almost no extractable text (scanned?): {NO_OCR}")
            text, warnings = _ocr_pages(doc, ocr, max_ocr_pages)
            figures = []  # the pages are images: showing them all as figures would only add noise
        else:
            figures = _figures(doc)
    title = meta_title.strip() or fallback_title.replace("-", " ").replace("_", " ").strip()
    return ExtractedDoc(
        title=title,
        text=text.strip(),
        kind="paper",
        pdf_bytes=data,
        figures=figures,
        warnings=warnings,
    )
