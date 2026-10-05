"""The text of a PDF, as Markdown: what the extractor makes of PDFium's lines, tested on committed
PDFs (tests/fixtures/pdf/) written by another library, so the layout is not our own idea."""

import io
import re

import pypdfium2 as pdfium
import pytest
from pdf_fixtures import pdf_bytes

from esbi_cli.extract import ExtractError
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.extract.pdf_text import Line, clean_text, lines_to_markdown
from esbi_cli.ingest.apply import _quotes


def text_of(name: str) -> str:
    return extract_pdf_bytes(pdf_bytes(name), "x").text


def two_pages_of_the_paper() -> bytes:
    """pages 1-2 of paper.pdf: the running header is on only two pages here, the page numbers are not."""
    out, source = pdfium.PdfDocument.new(), pdfium.PdfDocument(pdf_bytes("paper.pdf"))
    out.import_pages(source, [0, 1])
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


def test_headings_are_found_by_size_and_by_weight_and_numbering_gives_their_level():
    lines = text_of("paper.pdf").splitlines()

    assert "# Attention Helps Small Models" in lines  # the biggest text is the title
    assert "## Abstract" in lines  # bold, same size as the body
    assert "## 1 Introduction" in lines and "## 2 Method" in lines
    assert "### 2.1 Training" in lines  # one level down for each dot of the number
    assert "## References" in lines  # chunking cuts the bibliography at this line


def test_lines_become_paragraphs_a_gap_or_an_indent_starts_a_new_one():
    text = text_of("paper.pdf")

    assert "faster than recurrent ones.\n\nA second paragraph begins here" in text  # a gap
    assert (
        "eight GPUs.\n\nA new paragraph is marked by an indent only. It has a second line" in text
    )
    assert "Costs are low.\n\nCode is open." in text  # short sentences, one per line, no gap
    assert (
        "Recurrent networks process tokens one at a time, so training is slow. Models that" in text
    )


def test_a_sentence_goes_on_across_a_column_and_a_word_across_a_line_break():
    text = text_of("paper.pdf")

    # the left column ends in the middle of a sentence and the word `single` is cut by a hyphen
    assert "easy to train with a single learning rate. Training used eight GPUs." in text


def test_a_hyphen_at_the_end_of_a_line_is_dropped_in_a_word_and_kept_in_a_compound():
    text = text_of("paper.pdf")

    assert "self-attention enables small models" in text  # en-/ables was one word
    assert (
        "with a feed-forward network" in text
    )  # feed-/forward is a compound the paper also hyphenates
    assert "en-" not in text and "\ufffe" not in text


def test_running_headers_and_page_numbers_are_not_text():
    text = text_of("paper.pdf")

    assert text.count("Attention Helps Small Models") == 1  # the title; not the header of 3 pages
    assert not re.search(r"^\d$", text, re.M)


def test_page_numbers_go_even_when_there_are_too_few_pages_to_tell_a_header():
    text = extract_pdf_bytes(two_pages_of_the_paper(), "x").text

    assert not re.search(r"^\d$", text, re.M)
    assert text.count("Attention Helps Small Models") == 3  # title and two headers: kept, not sure


def test_table_rows_stay_one_per_line_so_a_model_can_read_the_columns():
    text = text_of("paper.pdf")

    assert "Base 65 27.3 3.3\nBig 213 28.4 2.3" in text


def test_a_sentence_with_numbers_is_not_taken_for_a_table_row():
    text = text_of("paper.pdf")

    assert "of the input length. Cost: 3.5 days, 8 GPUs, 2 nodes." in text  # ends in a period
    assert "trained for 3.5 days on 8 GPUs with 2 nodes and no extra data and mentions" in text


def test_a_caption_is_a_paragraph_of_its_own():
    text = text_of("text-over-images.pdf")

    assert "\n\nFigure 1: A picture with a label\n\n" in text  # a page ends here
    assert "and in the next\n\nFigure 3: Costs of training\n\n" in text_of(
        "paper.pdf"
    )  # a line goes on


def test_the_numbers_of_a_chart_axis_are_not_text_but_a_short_list_is():
    text = text_of("chart-labels.pdf")

    assert "The chart below shows the scores" in text and "The scores grow with" in text
    assert not re.search(r"\b140\b", text)  # the axis of the chart: 0, 10, 20 ... 140
    assert "1 item 2 item 3 item 4 item 5 item" in text
    assert "Planning Memory Tools" in text  # fourteen words in a column are a list, not a chart


def test_text_over_a_picture_is_its_label_but_text_over_a_whole_page_scan_is_the_scans_text():
    text = text_of("text-over-images.pdf")

    assert "Label inside the picture" not in text
    assert "El texto del artículo habla de agentes" in text
    assert "Texto reconocido de una página escaneada" in text


def test_a_quote_copied_from_the_text_passes_the_guard_even_across_a_healed_hyphen():
    text = text_of("paper.pdf")
    sentence = "Attention helps small models read long inputs, and it does so with less training cost than recurrent models."
    across_the_hyphen = "how self-attention enables small models to read long inputs"

    assert _quotes([sentence, across_the_hyphen], text) == [sentence, across_the_hyphen]


def test_a_pdf_with_less_text_than_a_paper_is_taken_for_a_scan_and_says_so():
    with pytest.raises(ExtractError, match="almost no extractable text"):
        extract_pdf_bytes(pdf_bytes("little-text.pdf"), "x")


def test_whatever_pdfium_raises_while_reading_a_page_is_an_extract_error(monkeypatch):
    from esbi_cli.extract import pdf

    def broken(doc):
        raise ValueError("Crop exceeds page dimensions")

    monkeypatch.setattr(pdf, "document_lines", broken)

    with pytest.raises(ExtractError, match="Could not read PDF: Crop exceeds"):
        extract_pdf_bytes(pdf_bytes("paper.pdf"), "x")


def test_a_file_that_is_not_a_pdf_or_needs_a_password_is_an_extract_error():
    with pytest.raises(ExtractError, match="Could not open PDF"):
        extract_pdf_bytes(b"this is not a pdf at all", "x")
    with pytest.raises(ExtractError, match="Could not open PDF"):
        extract_pdf_bytes(pdf_bytes("locked.pdf"), "x")


def test_a_truncated_pdf_is_an_extract_error_not_a_crash():
    data = pdf_bytes("paper.pdf")
    try:
        extract_pdf_bytes(data[: len(data) // 2], "x")
    except ExtractError:
        pass  # either it is read as far as it goes or it is refused cleanly


def line(text: str, y: float, size: float = 10.0) -> Line:
    return Line(text, size, False, 50, 400, y, 1, 800, False)


def body(count: int = 300) -> list[Line]:
    return [line("Some text of the body of the document goes here for a while.", 20)] * count


def test_more_than_two_hundred_big_lines_are_chart_labels_or_slides_not_headings():
    big = [line(f"Slide title number {n}", 700 - n * 30, 20.0) for n in range(201)]

    assert "#" not in lines_to_markdown(big + body())
    assert lines_to_markdown(big[:5] + body()).startswith("# ")  # few big lines: headings


def test_a_big_line_is_a_heading_only_if_it_is_short_and_does_not_end_like_a_sentence():
    long_line = line(
        "A line of big text that goes on and on for far more than a hundred characters " * 2,
        700,
        20.0,
    )
    sentence = line("Big text that ends like a sentence.", 600, 20.0)
    title = line("A short title", 500, 20.0)

    text = lines_to_markdown([long_line, sentence, title] + body())

    assert text.count("#") == 1 and "# A short title" in text


def test_a_heading_that_wraps_onto_a_second_line_is_one_heading_but_two_apart_are_two():
    wrapped = [line("A title that is long", 700, 20.0), line("and goes on", 678, 20.0)]
    apart = [line("A title", 700, 20.0), line("Another title", 500, 20.0)]

    assert "# A title that is long and goes on" in lines_to_markdown(wrapped + body())
    assert lines_to_markdown(apart + body()).count("# ") == 2


def test_ligatures_are_spelled_out_and_control_characters_removed():
    assert (
        clean_text("e\ufb03cient \ufb01rst \ufb02ow\x01 text\ufffd") == "efficient first flow text"
    )
