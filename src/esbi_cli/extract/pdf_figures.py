"""Figures of a PDF, and PDF pages, as PNG images rendered by PDFium.

A figure is an image of at least 100x80 points, or a drawing (vector graphics) with a caption
`Figure N` printed next to it. Everything is rendered at a bounded size: a hostile PDF can claim
a huge image or draw one picture hundreds of times.
"""

import hashlib
import io
import re
from dataclasses import dataclass
from itertools import islice

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from esbi_cli.extract import Figure
from esbi_cli.extract.pdf_text import Line, Rect, is_row

CAPTION = re.compile(r"\s*(figure|fig\.?|figura)\s*\d+", re.I)
TABLE_CAPTION = re.compile(r"\s*(table|tabla)\s*\d+", re.I)
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
PANEL_GAP_POINTS = 120  # the panels of one figure, under one caption, are this close to each other
MAX_PANEL_OBJECTS = 300  # more drawing objects than this beside a figure: no panels are looked for
MAX_PAGE_IMAGES = 500  # distinct pictures of a page that we look at
BESIDE_POINTS = 400  # a caption this far above, in another column, bounds the figure's columns
MIN_TABLE_ROWS = 3  # rows of numbers in a drawing this many make it a table, not a panel


def _overlap(a: Rect, b: Rect) -> float:
    """The area shared by two rectangles."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(r: Rect) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _is_figure_sized(r: Rect) -> bool:
    w, h = r[2] - r[0], r[3] - r[1]
    return w >= MIN_WIDTH_POINTS and h >= MIN_HEIGHT_POINTS and max(w / h, h / w) <= MAX_ASPECT


def _too_busy(page) -> bool:
    """More objects than MAX_PAGE_OBJECTS, counting those inside forms (a page of one form is one
    object at the top). Counting stops one past the cap, so a huge page costs no more than that."""
    return sum(1 for _ in islice(page.get_objects(), MAX_PAGE_OBJECTS + 1)) > MAX_PAGE_OBJECTS


def _objects(page, kind: int) -> list[Rect]:
    """Bounds of the page's objects of one kind, each distinct rectangle once: a page can draw
    one image hundreds of times, and rendering every one would take minutes. Objects inside a
    form (an XObject placed by a matrix) are given where the forms place them on the page."""
    if page.get_rotation() or _too_busy(page):
        return []  # ponytail: PDFium crops after rotating, so a rotated page gets no figures
    box = page.get_cropbox()
    seen: dict[tuple[int, ...], Rect] = {}
    for obj in page.get_objects(filter=[kind]):
        bounds, form = obj.get_bounds(), obj.container  # PDFium gives the form's own coordinates
        while form:
            bounds, form = form.get_matrix().on_rect(*bounds), form.container
        left, bottom, right, top = bounds
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


def _captions(lines: list[Line], pattern: re.Pattern[str] = CAPTION) -> list[Caption]:
    """The captions of a page: a line starting `Figure N` (or `Table N`) and the lines of its block."""
    captions = []
    for first, line in enumerate(lines):
        if not pattern.match(line.text):
            continue
        block, previous = [line], line
        for nxt in islice(lines, first + 1, None):
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


def _caption_for(rect: Rect, captions: list[Caption]) -> tuple[str, bool] | None:
    """The caption printed just below the figure (or just above it), in the figure's columns, and
    whether it is below."""
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
    return (nearest[0][1], bool(below)) if nearest else None


def _union(boxes: list[Rect]) -> Rect:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _near(a: Rect, b: Rect, gap: float) -> bool:
    """Are two rectangles within `gap` points of each other, or touching?"""
    return a[0] - gap <= b[2] and b[0] <= a[2] + gap and a[1] - gap <= b[3] and b[1] <= a[3] + gap


def _groups(boxes: list[Rect], gap: float = GROW_POINTS) -> list[tuple[Rect, int]]:
    """The drawings that the boxes make up, each with its number of objects: boxes within `gap`
    points of each other belong together, directly or through other boxes. One pass over the
    pairs, so a chain of 300 boxes costs 45,000 comparisons, not millions."""
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, box in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            if _near(box, boxes[j], gap):
                parent[find(i)] = find(j)
    members: dict[int, list[Rect]] = {}
    for i, box in enumerate(boxes):
        members.setdefault(find(i), []).append(box)
    return [(_union(group), len(group)) for group in members.values()]


def _is_table(box: Rect, rows: list[Line]) -> bool:
    """Rows of numbers inside a drawing: a table (a figure's labels are rarely rows of numbers)."""
    inside = [
        ln
        for ln in rows
        if box[0] - 2 <= (ln.left + ln.right) / 2 <= box[2] + 2
        and box[1] - 2 <= ln.baseline <= box[3] + 2
    ]
    return len(inside) >= MIN_TABLE_ROWS


def _with_panels(region: Rect, rest: list[Rect], lines: list[Line]) -> Rect:
    """The other drawings under the same caption: the panels of a figure stand further apart than
    the parts of a drawing. A table is no panel."""
    if not rest or len(rest) > MAX_PANEL_OBJECTS:
        return region
    rows = [ln for ln in lines if is_row(ln)]
    panels = [(box, n) for box, n in _groups(rest) if n >= MIN_PATHS and not _is_table(box, rows)]
    grew = True
    while grew:
        grew = False
        for panel in list(panels):
            if _near(region, panel[0], PANEL_GAP_POINTS):
                region = _union([region, panel[0]])
                panels.remove(panel)
                grew = True
    return region


def _drawn_region(
    page, cap: Caption, lines: list[Line], paths: list[Rect], others: list[Caption] = ()
) -> Rect | None:
    """The drawing directly above a caption: the drawing objects that touch it, grown outwards,
    stopping at the paragraph of text above, and joined by the panels beside it. It keeps to the
    caption's columns: as wide as the paragraphs that share them, but not into the column of
    another caption (a table beside the figure)."""
    cap_top = cap.line.baseline + cap.line.size
    column = [
        ln
        for ln in lines
        if len(ln.text) >= PROSE_CHARS and min(ln.right, cap.right) > max(ln.left, cap.left)
    ]
    x0 = min([cap.left, *(ln.left for ln in column)]) - 15
    x1 = max([cap.right, *(ln.right for ln in column)]) + 15
    above = [
        o for o in others if o is not cap and cap_top < o.line.baseline < cap_top + BESIDE_POINTS
    ]
    beside = False
    for other in above:  # a caption in another column: its table or picture is not ours
        if other.right <= cap.left:
            x0, beside = max(x0, other.right + 4), True
        elif other.left >= cap.right:
            x1, beside = min(x1, other.left - 4), True
    stop = min(  # the nearest paragraph, or caption of another figure, above in the same columns
        [
            ln.baseline
            for ln in lines
            if len(ln.text) >= PROSE_CHARS
            and ln.baseline > cap_top
            and min(ln.right, x1) > max(ln.left, x0)
        ]
        + [o.line.baseline for o in above if min(o.right, x1) > max(o.left, x0)],
        default=page.get_height(),
    )
    usable = [  # beside another column's table, an object belongs to us by its middle
        p
        for p in paths
        if p[1] >= cap_top - 2
        and p[3] <= stop + 2
        and (x0 <= (p[0] + p[2]) / 2 <= x1 if beside else min(p[2], x1) > max(p[0], x0))
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
    region = _with_panels(region, [p for p, t in zip(usable, taken, strict=True) if not t], lines)
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
    others = [*captions, *_captions(lines, TABLE_CAPTION)]
    regions: list[tuple[Rect, str]] = []
    for cap in captions[:MAX_CAPTIONS_PER_PAGE]:
        region = _drawn_region(page, cap, lines, paths, others)
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
        panels: dict[tuple[str, bool], list[Rect]] = {}  # the pictures that share a caption
        for rect in images.get(index, [])[:MAX_PAGE_IMAGES]:
            if any(_overlap(rect, d) > 0.5 * _area(rect) for d in drawn_by_page[index]):
                continue  # a picture inside a drawn figure
            caption = _caption_for(rect, captions)
            if caption:  # on the same side of it: a picture below a caption is not its figure's
                panels.setdefault(caption, []).append(rect)
            elif _is_figure_sized(rect):
                candidates.append((index + 1, rect, None))
        for (caption, _), rects in panels.items():
            # the panels of a figure may each be smaller than a figure: they count together
            boxes = (
                _groups(rects, PANEL_GAP_POINTS)
                if len(rects) <= MAX_PANEL_OBJECTS
                else [(r, 1) for r in rects]
            )
            candidates.extend(
                (index + 1, box, caption) for box, _ in boxes if _is_figure_sized(box)
            )
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
