"""Figures of a PDF, and PDF pages, as PNG images rendered by PDFium.

A figure is an image of at least 100x80 points, or a drawing (vector graphics) with a caption
`Figure N` printed next to it. Everything is rendered at a bounded size: a hostile PDF can claim
a huge image or draw one picture hundreds of times.
"""

import hashlib
import io
import re
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from esbi_cli.extract import Figure
from esbi_cli.extract.pdf_text import Line, Rect

CAPTION = re.compile(r"\s*(figure|fig\.?|figura)\s*\d+", re.I)
MAX_FIGURES = 8
MIN_WIDTH_POINTS, MIN_HEIGHT_POINTS = (
    100,
    80,
)  # PDF points: smaller images are icons, logos, bullets
MAX_ASPECT = 6  # thinner strips are rules and banners, not figures
FIGURE_DPI = 150
MAX_FIGURE_PX = 3000
MAX_PAGE_OBJECTS = 20000  # a page with more drawing operations than this is not worth the time
MAX_DRAWN_PATHS = 1000  # distinct lines and shapes on a page that we try to group into a figure
MAX_CAPTIONS_PER_PAGE = 6  # captions on a page that we look for a drawing for
MIN_PATHS = 8  # a drawing with fewer lines and shapes than this is a rule or a box, not a figure
CAPTION_BELOW_POINTS, CAPTION_ABOVE_POINTS = 90, 60  # how far from its figure a caption may be
CAPTION_MAX_CHARS = 200
PROSE_CHARS = 50  # a text line this long is a paragraph, which ends a drawing
GROW_POINTS = 30  # the parts of a drawing, and its subfigures, are this close to each other
PAD_POINTS = 12  # a drawn figure's labels sit just outside its lines


def _overlap(a: Rect, b: Rect) -> float:
    """The area shared by two rectangles."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(r: Rect) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _is_figure_sized(r: Rect) -> bool:
    w, h = r[2] - r[0], r[3] - r[1]
    return w >= MIN_WIDTH_POINTS and h >= MIN_HEIGHT_POINTS and max(w / h, h / w) <= MAX_ASPECT


def _objects(page, kind: int) -> list[Rect]:
    """Bounds of the page's objects of one kind, each distinct rectangle once: a page can draw
    one image hundreds of times, and rendering every one would take minutes."""
    if page.get_rotation() or pdfium_raw.FPDFPage_CountObjects(page.raw) > MAX_PAGE_OBJECTS:
        return []  # ponytail: PDFium crops after rotating, so a rotated page gets no figures
    box = page.get_cropbox()
    seen: dict[tuple[int, ...], Rect] = {}
    for obj in page.get_objects(filter=[kind]):
        left, bottom, right, top = obj.get_bounds()
        # what is drawn off the page cannot be seen, and cannot be rendered
        rect = (max(left, box[0]), max(bottom, box[1]), min(right, box[2]), min(top, box[3]))
        if rect[2] > rect[0] and rect[3] > rect[1]:
            seen.setdefault(tuple(round(v) for v in rect), rect)
    return list(seen.values())


def page_images(page) -> list[Rect]:
    return _objects(page, pdfium_raw.FPDF_PAGEOBJ_IMAGE)


@dataclass
class Caption:
    line: Line  # the first line, `Figure N: ...`
    text: str
    left: float  # the extent of all its lines
    right: float


def _captions(lines: list[Line]) -> list[Caption]:
    """The figure captions of a page: a line starting `Figure N` and the lines of its block."""
    captions = []
    for first, line in enumerate(lines):
        if not CAPTION.match(line.text):
            continue
        block, previous = [line], line
        for nxt in lines[first + 1 :]:
            if not 0 < previous.baseline - nxt.baseline < nxt.size * 1.8:
                break
            if abs(nxt.left - previous.left) > 20:
                break
            block.append(nxt)
            previous = nxt
        text = " ".join(" ".join(ln.text for ln in block).split())[:CAPTION_MAX_CHARS]
        captions.append(
            Caption(line, text, min(b.left for b in block), max(b.right for b in block))
        )
    return captions


def _caption_for(rect: Rect, captions: list[Caption]) -> str | None:
    """The caption printed just below the figure (or just above it), in the figure's columns."""
    below, above = [], []
    for cap in captions:
        if min(cap.right, rect[2]) <= max(cap.left, rect[0]):
            continue  # beside the figure, not under it
        top, bottom = cap.line.baseline + cap.line.size, cap.line.baseline - cap.line.size * 0.25
        if rect[1] - CAPTION_BELOW_POINTS < top <= rect[1] + 5:
            below.append((rect[1] - top, cap.text))
        if 0 <= bottom - rect[3] < CAPTION_ABOVE_POINTS:
            above.append((bottom - rect[3], cap.text))
    nearest = sorted(below) or sorted(above)
    return nearest[0][1] if nearest else None


def _union(boxes: list[Rect]) -> Rect:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _drawn_region(page, cap: Caption, lines: list[Line], paths: list[Rect]) -> Rect | None:
    """The drawing directly above a caption: the drawing objects that touch it, grown outwards,
    stopping at the paragraph of text above. It keeps to the caption's columns: as wide as the
    paragraphs that share them."""
    cap_top = cap.line.baseline + cap.line.size
    column = [
        ln
        for ln in lines
        if len(ln.text) >= PROSE_CHARS and min(ln.right, cap.right) > max(ln.left, cap.left)
    ]
    x0 = min([cap.left, *(ln.left for ln in column)]) - 15
    x1 = max([cap.right, *(ln.right for ln in column)]) + 15
    stop = min(  # the nearest paragraph above, in the same columns
        (
            ln.baseline
            for ln in lines
            if len(ln.text) >= PROSE_CHARS
            and ln.baseline > cap_top
            and min(ln.right, x1) > max(ln.left, x0)
        ),
        default=page.get_height(),
    )
    usable = [
        p
        for p in paths
        if p[1] >= cap_top - 2 and p[3] <= stop + 2 and min(p[2], x1) > max(p[0], x0)
    ]
    taken = [p[1] <= cap_top + 40 for p in usable]  # the objects that touch the caption's area
    if not any(taken):
        return None
    region = _union([p for p, t in zip(usable, taken, strict=True) if t])
    grew = True
    while grew:  # take in every object within GROW_POINTS of the drawing, and so on
        grew = False
        near = (
            region[0] - GROW_POINTS,
            region[1] - GROW_POINTS,
            region[2] + GROW_POINTS,
            region[3] + GROW_POINTS,
        )
        for k, p in enumerate(usable):
            if not taken[k] and _overlap(near, p):
                taken[k] = True
                region = _union([region, p])
                grew = True
    if sum(taken) < MIN_PATHS:
        return None
    labels = [  # short lines of text are the figure's labels; paragraphs are not
        (ln.left, ln.baseline - ln.size * 0.25, ln.right, ln.baseline + ln.size)
        for ln in lines
        if len(ln.text) < PROSE_CHARS and cap_top < ln.baseline <= stop
    ]
    for _ in range(3):  # a label can lead to the next one
        near = (
            region[0] - PAD_POINTS,
            region[1] - PAD_POINTS,
            region[2] + PAD_POINTS,
            region[3] + PAD_POINTS,
        )
        region = _union([region, *(box for box in labels if _overlap(near, box))])
    return (region[0] - 2, max(region[1] - 2, cap_top + 1), region[2] + 2, region[3] + 2)


def _drawn_regions(page, lines: list[Line], captions: list[Caption]) -> list[tuple[Rect, str]]:
    """Drawn figures (vector graphics) of a page with their captions: only a caption makes a
    drawing a figure, because tables and page decorations are drawn too."""
    if not captions:
        return []
    paths = [
        p
        for p in _objects(page, pdfium_raw.FPDF_PAGEOBJ_PATH)
        if not (p[2] - p[0] > page.get_width() * 0.9 and p[3] - p[1] > page.get_height() * 0.9)
        and (p[2] - p[0] > 1.5 or p[3] - p[1] > 1.5)
    ]
    if len(paths) > MAX_DRAWN_PATHS:
        return []  # a plot of thousands of marks: not worth growing a region through them
    regions: list[tuple[Rect, str]] = []
    for cap in captions[:MAX_CAPTIONS_PER_PAGE]:
        region = _drawn_region(page, cap, lines, paths)
        # two captions of one drawing give the same picture twice: rendering keeps it once
        if region and _is_figure_sized(region):
            regions.append((region, cap.text))
    return regions


def render_png(page, rect: Rect | None, dpi: int, max_px: int) -> bytes:
    """`rect` (or the whole page) as a PNG at `dpi`, lowered so that no side passes `max_px`."""
    left, bottom, right, top = page.get_cropbox()
    rect = rect or (left, bottom, right, top)
    x0, y0, x1, y1 = (
        max(rect[0], left),
        max(rect[1], bottom),
        min(rect[2], right),
        min(rect[3], top),
    )
    scale = min(dpi, max_px * 72 / max(x1 - x0, y1 - y0, 1)) / 72
    image = page.render(scale=scale, crop=(x0 - left, y0 - bottom, right - x1, top - y1)).to_pil()
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


Candidate = tuple[int, Rect, str | None]  # page number, rectangle, caption


def locate_figures(
    doc: pdfium.PdfDocument, pages: list[list[Line]], images: dict[int, list[Rect]]
) -> tuple[list[Candidate], dict[int, list[Rect]]]:
    """Where the figures are: images and drawn figures with their captions, and the drawn
    figures' rectangles by page index (their labels are not prose). Nothing is rendered yet."""
    candidates: list[Candidate] = []
    drawn_by_page: dict[int, list[Rect]] = {}
    for index, lines in enumerate(pages):
        captions = _captions(lines)
        drawn = _drawn_regions(doc[index], lines, captions)
        drawn_by_page[index] = [rect for rect, _ in drawn]
        candidates.extend((index + 1, rect, text) for rect, text in drawn)
        for rect in images.get(index, []):
            covered = any(_overlap(rect, d) > 0.5 * _area(rect) for d in drawn_by_page[index])
            if _is_figure_sized(rect) and not covered:
                candidates.append((index + 1, rect, _caption_for(rect, captions)))
    return candidates, drawn_by_page


def render_figures(doc: pdfium.PdfDocument, candidates: list[Candidate]) -> list[Figure]:
    """Up to MAX_FIGURES real figures: the captioned ones first, then the biggest."""
    candidates = sorted(candidates, key=lambda c: (c[2] is None, -_area(c[1])))
    figures, seen = [], set()
    for number, rect, caption in candidates:
        if len(figures) == MAX_FIGURES:
            break
        # rendering the figure's area (not extracting the raw stream) keeps masks and overlays right
        data = render_png(doc[number - 1], rect, FIGURE_DPI, MAX_FIGURE_PX)
        digest = hashlib.sha1(data).hexdigest()
        if digest not in seen:
            seen.add(digest)
            figures.append(Figure(data=data, page=number, caption=caption))
    return sorted(figures, key=lambda f: f.page)  # reading order
