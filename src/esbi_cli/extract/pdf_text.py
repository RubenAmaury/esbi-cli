"""The text of a PDF as plain Markdown, built from PDFium's characters.

PDFium gives text in reading order with the font size and weight of every character, and nothing
else: no paragraphs, headings or tables. This module adds what the notes need: lines are reflowed
into paragraphs, line-end hyphens are healed, running headers and chart labels are dropped, and
headings are found by font size and weight. Table rows stay one per line. The output has no
emphasis markers, so the model copies sentences that are verbatim in the text.
"""

import ctypes
import re
from collections import Counter
from dataclasses import dataclass
from statistics import median

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

Rect = tuple[float, float, float, float]  # left, bottom, right, top in PDF points (y grows up)

HYPHEN_CODE = 0x02  # what PDFium puts where a line ended in a hyphen (its text shows U+FFFE)
LINE_BREAKS = (0x0D, 0x0A)
HEADING_SIZE_RATIO = 1.12  # a line this much bigger than the body text is a heading
MAX_HEADING_CHARS = 100
MIN_HEADING_CAP = 40  # a document has at most this many headings, or HEADINGS_PER_PAGE a page,
HEADINGS_PER_PAGE = 8  # whichever is more: the rest are chart labels, and the best ones are kept
MARGIN_FRACTION = 0.07  # top and bottom strips of a page where running headers and numbers live
MIN_REPEATS = 3  # a margin line on this many pages is a running header or footer
MIN_CHART_RUN = 12  # this many label-like lines in a row are the text of a chart
MAX_COVER_FRACTION = (
    0.6  # text over an image bigger than this part of the page is a scan's text layer
)
MAX_LABEL_CHARS, MAX_LABEL_WORDS = 60, 8  # a label that a chart repeats is a fragment this short
MAX_CLUSTER_CHARS = 30  # the lines of a chart cluster are shorter still
MIN_LABEL_REPEATS = 8  # a fragment that appears this often in a document is a chart label
CLUSTER_CELL_POINTS = 50  # a region of 3x3 cells of this size...
MIN_CLUSTER_LINES = 40  # ...with this many short lines is the text of a chart, not of a page
MIN_ROW_NUMBERS = 2  # a line with this many numbers, and mostly numbers, is a table row
ROW_NUMBER_SHARE = 0.3  # share of a table row's words that are numbers
PARAGRAPH_GAP = 1.3  # a gap between lines this many times the usual one starts a paragraph

_NUMBERED = re.compile(r"^(\d{1,2}(\.\d{1,2}){0,3}\.?|[A-Z]\.|Abstract|Appendix)(\s|$)")
_CAPTION_START = re.compile(r"^(figure|fig\.|table|figura|tabla)\s*\d+[.:]", re.I)
_DEPTH = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s")
_REFERENCES = re.compile(r"^(references|referencias|bibliography|bibliografía)$", re.I)
_NUMBER = re.compile(r"(?<![\w.])[-+(]?\d+(?:[.,]\d+)?%?\)?(?![\w.])")
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\ufffd]")
_LIGATURES = str.maketrans(
    {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
)


@dataclass
class Line:
    text: str
    size: float  # font size in points
    bold: bool
    left: float
    right: float
    baseline: float  # y of the line's baseline
    page: int  # 1-based
    page_height: float
    hyphen: bool = False  # the line ended in a hyphen that PDFium marked: the word goes on below


def _baseline(textpage, first: int, last: int) -> float:
    """The baseline of a line: the median over a few characters, so that a superscript or a
    subscript does not move it."""
    ys = []
    for index in {first + (last - first) * k // 4 for k in range(5)}:
        x, y = ctypes.c_double(), ctypes.c_double()
        pdfium_raw.FPDFText_GetCharOrigin(textpage.raw, index, x, y)
        ys.append(y.value)
    return median(ys)


def _is_bold(textpage, index: int) -> bool:
    """By the font's weight, or by its name: PDFium reports 545 for LMRoman12-Bold."""
    if pdfium_raw.FPDFText_GetFontWeight(textpage.raw, index) >= 600:
        return True
    name = ctypes.create_string_buffer(128)
    pdfium_raw.FPDFText_GetFontInfo(textpage.raw, index, name, 128, ctypes.c_int())
    return any(word in name.value.lower() for word in (b"bold", b"black", b"heavy"))


def _is_blank(code: int) -> bool:
    return code == 0 or (code <= 0x10FFFF and chr(code).isspace())


def _line(textpage, codes: list[int], start: int, stop: int, **fields) -> Line | None:
    """The line made of characters start..stop of the page, or None if it holds only blanks."""
    shown = [i for i in range(start, stop) if not _is_blank(codes[i])]
    if not shown:
        return None
    first, last = shown[0], shown[-1]
    middle = shown[len(shown) // 2]
    left, _, _, _ = textpage.get_charbox(first, loose=True)
    _, _, right, _ = textpage.get_charbox(last, loose=True)
    return Line(
        text=textpage.get_text_range(index=first, count=last - first + 1).strip(),
        size=round(pdfium_raw.FPDFText_GetFontSize(textpage.raw, middle), 1),
        bold=_is_bold(textpage, middle),
        left=left,
        right=right,
        baseline=_baseline(textpage, first, last),
        **fields,
    )


def page_lines(page, number: int) -> list[Line]:
    """The text lines of a page, in PDFium's reading order, with font and position. Lines are cut
    on PDFium's own characters, not on its text, because the two do not line up: a character with
    no Unicode value (U+0000) is counted but left out of the text, and so shifts every index."""
    textpage = page.get_textpage()
    codes = [pdfium_raw.FPDFText_GetUnicode(textpage.raw, i) for i in range(textpage.count_chars())]
    lines, start = [], 0
    for index, code in enumerate([*codes, LINE_BREAKS[0]]):  # the extra one ends the last line
        if code in LINE_BREAKS or code == HYPHEN_CODE:
            line = _line(
                textpage,
                codes,
                start,
                index,
                page=number,
                page_height=page.get_height(),
                hyphen=code == HYPHEN_CODE,
            )
            if line:
                lines.append(line)
            start = index + 1
    return lines


def _inside(line: Line, rects: list[Rect]) -> bool:
    x, y = (line.left + line.right) / 2, line.baseline + line.size * 0.3
    return any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects)


def _is_label(line: Line) -> bool:
    """A short fragment, as found on the axes and legends of a chart."""
    return (
        len(line.text) <= 24
        and len(line.text.split()) <= 3
        and not line.text.endswith((".", ":"))
        and (len(line.text) <= 3 or any(c.isdigit() for c in line.text))
    )


def _is_fragment(line: Line) -> bool:
    """A few words that do not end like a sentence: a label, never a line of a paragraph."""
    text = line.text
    return (
        len(text) <= MAX_LABEL_CHARS
        and len(text.split()) <= MAX_LABEL_WORDS
        and not text.endswith((".", ":", ";", ",", "?", "!"))
    )


def _in_a_row_of_prose(lines: list[Line], index: int, repeats: Counter[str]) -> bool:
    """Is the line a piece of a line of prose? PDFium cuts a line where a formula changes the font
    or the height, so `V` and `g` in `where V g is` are lines of their own, on the row of the text.
    A long line that is said many times is not prose either, but the text of a chart."""
    line = lines[index]
    return any(
        other.page == line.page
        and not _is_fragment(other)
        and repeats[other.text.lower()] < MIN_LABEL_REPEATS
        and abs(other.baseline - line.baseline) <= max(line.size, other.size) * 0.6
        for other in lines[max(0, index - 2) : index + 3]
    )


def _without_repeated_labels(lines: list[Line]) -> list[Line]:
    """Drop the fragments that a document says over and over (a legend drawn on every panel, an
    axis with the same ticks): prose does not repeat a line, and a figure drawn in layers repeats
    its text by the hundred. A symbol inside a line of prose stays."""
    repeats = Counter(ln.text.lower() for ln in lines)
    return [
        ln
        for i, ln in enumerate(lines)
        if not (
            _is_fragment(ln)
            and repeats[ln.text.lower()] >= MIN_LABEL_REPEATS
            and not _in_a_row_of_prose(lines, i, repeats)
        )
    ]


def _without_dense_clusters(lines: list[Line]) -> list[Line]:
    """Drop short lines packed into a small region of a page: the text of a chart. Real text, even
    a table, has a dozen lines in a region this size. The cells around the crowded one go too: a
    chart does not end where our grid does."""

    def cell(ln: Line) -> tuple[int, int, int]:
        x = (ln.left + ln.right) / 2
        return ln.page, int(x // CLUSTER_CELL_POINTS), int(ln.baseline // CLUSTER_CELL_POINTS)

    def around(page: int, i: int, j: int) -> list[tuple[int, int, int]]:
        return [(page, i + di, j + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)]

    short = [ln for ln in lines if len(ln.text) <= MAX_CLUSTER_CHARS]
    cells = Counter(cell(ln) for ln in short)
    crowded = {c for c in cells if sum(cells[n] for n in around(*c)) >= MIN_CLUSTER_LINES}
    chart = {n for c in crowded for n in around(*c)}
    return [ln for ln in lines if not (len(ln.text) <= MAX_CLUSTER_CHARS and cell(ln) in chart)]


def _without_chart_text(lines: list[Line]) -> list[Line]:
    """Drop the text of charts: repeated labels, dense clusters of them, and long runs of
    label-like lines (axes, legends, bar values)."""
    lines = _without_dense_clusters(_without_repeated_labels(lines))
    kept: list[Line] = []
    run: list[Line] = []

    def close() -> None:
        if len(run) < MIN_CHART_RUN:
            kept.extend(run)
        run.clear()

    for line in lines:
        if _is_label(line):
            if run and run[0].page != line.page:
                close()
            run.append(line)
        else:
            close()
            kept.append(line)
    close()
    return kept


def _without_margins(lines: list[Line]) -> list[Line]:
    """Drop page numbers and the headers and footers repeated on several pages."""

    def in_margin(line: Line) -> bool:
        y = line.baseline
        return y < line.page_height * MARGIN_FRACTION or y > line.page_height * (
            1 - MARGIN_FRACTION
        )

    def key(line: Line) -> str:
        return re.sub(r"\d+", "#", line.text.lower())

    pages_with = Counter(k for k, _ in {(key(ln), ln.page) for ln in lines if in_margin(ln)})
    return [
        line
        for line in lines
        if not (
            in_margin(line)
            and (_PAGE_NUMBER.match(line.text) or pages_with[key(line)] >= MIN_REPEATS)
        )
    ]


def _vocabulary(lines: list[Line]) -> set[str]:
    """The words of the document. Not the pieces of a word that a line break cut: `plicative` is
    no word, and counting it would make `multi` look like a word of its own."""
    words: set[str] = set()
    for previous, line in zip([None, *lines], lines, strict=False):
        text = line.text.lower()
        if line.hyphen:
            text = re.sub(r"[^\W\d_]+$", "", text)  # the first half of a word: it goes on below
        if previous is not None and previous.hyphen:
            text = re.sub(r"^[^\W\d_]+", "", text)  # and this is its second half
        words.update(re.findall(r"[^\W\d_]{2,}", text))
    return words


ENDINGS = ("s", "es", "d", "ed", "er", "ers", "ing", "ly", "ion", "ions", "ment", "ness", "ity")
# ponytail: a short list of first halves that make a phrase or a prefix, not a word: add as met
COMPOUND_HEADS = {"of", "in", "to", "as", "by", "on", "at", "for", "the", "and", "or", "non"}
MIN_COMPOUND_HEAD_CHARS = 4  # a first half this long that is a word of the document is a compound


def _is_known_word_with_ending(word: str, words: set[str]) -> bool:
    """`leveraged` is `leverage` and an ending, `omitted` is `omit` and a doubled letter and an
    ending, though the paper never says either word."""
    for cut_at in range(4, len(word)):
        stem, ending = word[:cut_at], word[cut_at:]
        endings = [ending, ending[1:]] if ending[:1] == stem[-1:] else [ending]
        if any(e in ENDINGS for e in endings) and (stem in words or stem + "e" in words):
            return True
    return False


def _keeps_hyphen(head: str, tail: str, words: set[str]) -> bool:
    """PDFium cannot tell a word broken at the line end (en-ables) from a compound that has a
    hyphen (feed-forward). The document can, a little: the joined word may be in it (or be a
    word of it with an ending), and the first half of a compound is a word, usually a long one,
    or a word like `of`; the second half of a broken word is no word of the document."""
    joined = head + tail
    if joined in words or _is_known_word_with_ending(joined, words):
        return False
    if head in COMPOUND_HEADS:
        return True
    return head in words and (tail in words or len(head) >= MIN_COMPOUND_HEAD_CHARS)


def _join(pieces: list[Line], words: set[str]) -> str:
    """The text of consecutive lines as one paragraph, with the marked line-end hyphens decided."""
    out = pieces[0].text
    for previous, line in zip(pieces, pieces[1:], strict=False):
        if not previous.hyphen:
            out += " " + line.text
            continue
        head, tail = re.search(r"[^\W\d_]+$", out), re.match(r"[^\W\d_]+", line.text)
        keep = head and tail and _keeps_hyphen(head.group().lower(), tail.group().lower(), words)
        out += ("-" if keep else "") + line.text
    return out


def _body_size(lines: list[Line]) -> float:
    sizes = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0]


def _is_heading(line: Line, body_size: float) -> bool:
    text = line.text
    if _REFERENCES.match(text):
        return True
    if len(text) > MAX_HEADING_CHARS or text.endswith((",", ".", ";")) or line.hyphen:
        return False
    if sum(c.isalpha() for c in text) < 3:
        return False
    return line.size >= body_size * HEADING_SIZE_RATIO or (
        line.bold and _NUMBERED.match(text) is not None
    )


def _best_headings(lines: list[Line], body_size: float) -> set[int]:
    """The indexes of the heading lines. A document can have only so many: more than that are the
    labels of a chart, and the numbered and the biggest lines are the likeliest headings."""
    found = [i for i, ln in enumerate(lines) if _is_heading(ln, body_size)]
    cap = max(MIN_HEADING_CAP, HEADINGS_PER_PAGE * max(ln.page for ln in lines))

    def rank(i: int) -> tuple[bool, float]:
        text = lines[i].text
        return bool(_NUMBERED.match(text) or _REFERENCES.match(text)), lines[i].size

    return set(sorted(found, key=rank, reverse=True)[:cap])  # a stable sort: the earlier wins


def _level(line: Line, head_sizes: list[float]) -> int:
    """`1 Intro` is ##, `3.1 Encoder` is ###; unnumbered headings rank by size (the title is #)."""
    depth = _DEPTH.match(line.text)
    if depth:
        return min(4, 2 + depth.group(1).count("."))
    if line.size in head_sizes:
        return min(3, 1 + head_sizes.index(line.size))
    return 2


def is_row(line: Line) -> bool:
    """A table row: mostly numbers, and not a sentence (a sentence ends in a period after a word)."""
    text = line.text
    numbers = len(_NUMBER.findall(text))
    sentence = text.endswith(".") and not text[-2:-1].isdigit()
    return (
        not sentence
        and numbers >= MIN_ROW_NUMBERS
        and numbers >= len(text.split()) * ROW_NUMBER_SHARE
    )


def _starts_paragraph(a: Line, b: Line, body_pitch: float, full_width: float) -> bool:
    """Does `b` start a new paragraph after `a`? A bigger gap than usual between the lines, a
    first-line indent, or a short line that ends a sentence."""
    if _CAPTION_START.match(b.text):
        return True
    ends_sentence = a.text.endswith((".", "?", "!", ":"))
    if a.page != b.page or b.baseline > a.baseline:  # a new page or column: join only mid-sentence
        return ends_sentence or _CAPTION_START.match(a.text) is not None
    if body_pitch and a.baseline - b.baseline > body_pitch * PARAGRAPH_GAP:
        return True
    if not ends_sentence:  # a hanging indent or a short line in the middle of a sentence
        return False
    return b.left > a.left + a.size * 0.8 or (a.right - a.left) < full_width * 0.6


def _full_widths(lines: list[Line]) -> dict[int, float]:
    """The width of a full line on each page (the 80th percentile of its line widths)."""
    widths: dict[int, list[float]] = {}
    for line in lines:
        widths.setdefault(line.page, []).append(line.right - line.left)
    return {page: sorted(w)[int(len(w) * 0.8)] for page, w in widths.items()}


def lines_to_markdown(lines: list[Line]) -> str:
    """Reflow the lines of a document into Markdown paragraphs, headings and table rows."""
    lines = _without_chart_text(lines)
    if not lines:
        return ""
    body = _body_size(lines)
    pitches = [
        a.baseline - b.baseline
        for a, b in zip(lines, lines[1:], strict=False)
        if a.page == b.page and a.size == b.size == body and 0 < a.baseline - b.baseline < body * 3
    ]
    body_pitch = median(pitches) if pitches else 0.0
    full = _full_widths(lines)
    words = _vocabulary(lines)
    headings = _best_headings(lines, body)
    head_sizes = sorted(
        {lines[i].size for i in headings if lines[i].size >= body * HEADING_SIZE_RATIO},
        reverse=True,
    )

    blocks: list[tuple[str, str]] = []  # (kind, text): kind is "heading", "rows" or "text"
    paragraph: list[Line] = []
    previous: Line | None = None

    def flush() -> None:
        if paragraph:
            blocks.append(("text", _join(paragraph, words)))
            paragraph.clear()

    for index, line in enumerate(lines):
        wraps = previous is not None and (
            previous.size == line.size
            and previous.page == line.page
            and 0 < previous.baseline - line.baseline < line.size * 2
        )
        if index in headings:
            flush()
            if (
                blocks
                and blocks[-1][0] == "heading"
                and wraps
                and len(blocks[-1][1]) + len(line.text) <= MAX_HEADING_CHARS
            ):
                blocks[-1] = ("heading", blocks[-1][1] + " " + line.text)  # a title on two lines
            else:
                blocks.append(("heading", f"{'#' * _level(line, head_sizes)} {line.text}"))
        elif is_row(line):
            flush()
            if blocks and blocks[-1][0] == "rows":
                blocks[-1] = ("rows", blocks[-1][1] + "\n" + line.text)
            else:
                blocks.append(("rows", line.text))
        else:
            if paragraph and _starts_paragraph(
                paragraph[-1], line, body_pitch, full.get(line.page, 0.0)
            ):
                flush()
            paragraph.append(line)
        previous = line
    flush()
    return "\n\n".join(text for _, text in blocks)


def clean_text(text: str) -> str:
    """Ligatures spelled out (the model copies `fi`, not U+FB01), control characters removed."""
    return _CONTROL.sub("", text.translate(_LIGATURES)).strip()


def document_lines(doc: pdfium.PdfDocument) -> list[list[Line]]:
    """The text lines of every page, with their control characters and ligatures cleaned."""
    pages = []
    for index in range(len(doc)):
        lines = page_lines(doc[index], index + 1)
        for line in lines:
            line.text = clean_text(line.text)
        pages.append([line for line in lines if line.text])
    return pages


def pdf_to_markdown(
    doc: pdfium.PdfDocument,
    pages: list[list[Line]],
    images: dict[int, list[Rect]],
    drawings: dict[int, list[Rect]],
) -> str:
    """The prose of the document as Markdown. Left out: text over an image or a drawn figure (its
    labels), chart labels, page numbers and running headers."""
    lines: list[Line] = []
    for index, page_lines_ in enumerate(pages):
        page_area = doc[index].get_width() * doc[index].get_height()
        covers = [
            r
            for r in images.get(index, [])
            if (r[2] - r[0]) * (r[3] - r[1]) < page_area * MAX_COVER_FRACTION
        ] + drawings.get(index, [])
        lines.extend(line for line in page_lines_ if not _inside(line, covers))
    return lines_to_markdown(_without_margins(lines))
