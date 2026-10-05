"""Figures: real images from PDFs (copied into the vault) and linked images from web pages."""

import io
from datetime import date

from conftest import FakeLLM, make_plan
from pdf_fixtures import pdf_bytes
from PIL import Image

from esbi_cli.extract import ExtractedDoc, Figure
from esbi_cli.extract.html import extract_html
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.ingest.pipeline import ingest

PNG = b"\x89PNG\r\n\x1a\n"


def size_of(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


def test_figures_are_extracted_as_png_with_their_caption_and_icons_are_skipped():
    doc = extract_pdf_bytes(
        pdf_bytes("figure-and-icon.pdf"), "paper"
    )  # a 300x200 figure and a 30x30 icon

    assert len(doc.figures) == 1
    fig = doc.figures[0]
    assert fig.page == 1 and fig.data.startswith(PNG)
    assert fig.caption.startswith("Figure 1") and "arnés" in fig.caption


def test_a_pdf_without_images_has_no_figures_and_the_same_image_is_kept_once():
    assert extract_pdf_bytes(pdf_bytes("plain-text.pdf"), "paper").figures == []

    assert len(extract_pdf_bytes(pdf_bytes("same-image-twice.pdf"), "paper").figures) == 1


def test_at_most_eight_figures_are_kept_captioned_ones_first_then_the_biggest():
    # pages 1-3: small but captioned; pages 4-12: bigger, no caption
    figures = extract_pdf_bytes(pdf_bytes("twelve-pages.pdf"), "paper").figures

    assert len(figures) == 8
    assert {1, 2, 3} <= {f.page for f in figures}  # every captioned figure made it
    assert [f.page for f in figures] == sorted(f.page for f in figures)  # in reading order


def test_a_figure_drawn_with_lines_and_boxes_is_found_by_its_caption_and_its_labels_are_not_text():
    doc = extract_pdf_bytes(pdf_bytes("drawn-figure.pdf"), "paper")

    # page 2: the same boxes without a caption; page 3: a caption over two big boxes (too few
    # objects); page 4: a caption over ten tiny boxes (too small); page 5: one drawing, two captions
    assert [f.page for f in doc.figures] == [
        1,
        5,
    ]  # and the picture inside page 1's drawing is no figure
    assert doc.figures[0].caption == "Figure 2: Pipeline of the system"
    assert doc.figures[1].caption.startswith("Figure 5: First caption")
    assert "Stage 1" not in doc.text and "Output" not in doc.text  # labels belong to the figure


def test_a_drawn_figure_stops_at_the_paragraph_above_it_and_takes_in_its_labels():
    width_px, height_px = size_of(
        extract_pdf_bytes(pdf_bytes("drawn-figure.pdf"), "paper").figures[0].data
    )

    assert (
        height_px < 400
    )  # a column rule runs from the top of the page to its bottom: not the figure
    assert width_px > 950  # the label `Output` stands just right of the last box


def test_each_drawn_figure_of_a_two_column_page_keeps_to_its_own_column():
    figures = extract_pdf_bytes(pdf_bytes("two-columns-drawn.pdf"), "paper").figures

    assert [f.caption for f in figures] == ["Figure 1: Left column", "Figure 2: Right column"]
    assert all(
        size_of(f.data)[0] < 500 for f in figures
    )  # a column is 200 points: 420 px at 150 dpi


def test_a_caption_is_found_above_a_figure_but_not_in_another_column():
    figures = extract_pdf_bytes(pdf_bytes("caption-above-and-beside.pdf"), "paper").figures

    assert [f.caption for f in figures] == ["Figure 4: Caption above its figure", None]


def test_a_thin_banner_is_not_a_figure():
    figures = extract_pdf_bytes(
        pdf_bytes("figure-and-icon.pdf"), "paper"
    ).figures  # also holds a 520 x 80 banner

    assert [f.caption[:8] for f in figures] == ["Figure 1"]


def test_only_the_first_captions_of_a_page_are_looked_at(monkeypatch):
    from esbi_cli.extract import pdf_figures

    calls = []
    real = pdf_figures._drawn_region
    monkeypatch.setattr(pdf_figures, "_drawn_region", lambda *a: calls.append(a) or real(*a))

    extract_pdf_bytes(pdf_bytes("many-captions.pdf"), "paper")  # ten captions on the page

    assert len(calls) == pdf_figures.MAX_CAPTIONS_PER_PAGE


def test_an_image_drawn_a_hundred_times_in_one_place_is_rendered_once(monkeypatch):
    from esbi_cli.extract import pdf_figures

    renders = []
    real = pdf_figures.render_png
    monkeypatch.setattr(
        pdf_figures, "render_png", lambda *a, **k: renders.append(a) or real(*a, **k)
    )

    figures = extract_pdf_bytes(pdf_bytes("same-image-100-times.pdf"), "paper").figures

    assert len(figures) == 1 and len(renders) == 1


def test_a_page_with_more_drawing_operations_than_the_cap_gets_no_figures(monkeypatch):
    from esbi_cli.extract import pdf_figures

    monkeypatch.setattr(pdf_figures, "MAX_PAGE_OBJECTS", 50)  # the page draws 100 images

    assert extract_pdf_bytes(pdf_bytes("same-image-100-times.pdf"), "paper").figures == []

    monkeypatch.setattr(
        pdf_figures, "MAX_DRAWN_PATHS", 5
    )  # the drawn figures hold 11 lines and boxes

    figures = extract_pdf_bytes(pdf_bytes("drawn-figure.pdf"), "paper").figures
    assert len(figures) == 1 and size_of(figures[0].data)[0] < 300  # only the picture inside page 1


def test_a_picture_partly_off_the_page_is_cut_at_the_page_and_one_wholly_off_it_is_skipped():
    figures = extract_pdf_bytes(pdf_bytes("off-page-image.pdf"), "paper").figures

    assert len(figures) == 1  # the other picture is at x 700-1000 on a page 595 wide
    assert size_of(figures[0].data) == (
        302,
        416,
    )  # the 145 x 200 points that can be seen, at 150 dpi


def test_a_page_turned_by_90_degrees_gets_no_figures_rather_than_a_wrong_crop():
    figures = extract_pdf_bytes(pdf_bytes("rotated-page.pdf"), "paper").figures

    assert [f.page for f in figures] == [1]  # page 2 holds the same picture, turned


def test_a_giant_picture_is_rendered_no_larger_than_the_clamp():
    doc = extract_pdf_bytes(pdf_bytes("huge-figure.pdf"), "paper")  # a 14400 x 14400 point page

    assert len(doc.figures) == 1 and max(size_of(doc.figures[0].data)) <= 3000


def article(images):
    body = "".join(
        f"<p>{'Un párrafo largo sobre agentes y su verificación automática. ' * 6}</p>"
        for _ in range(6)
    )
    return f"<html><head><title>Un artículo</title></head><body><article><h1>Un artículo</h1>{images}{body}</article></body></html>"


def test_web_pages_keep_links_to_their_content_images_but_not_icons_pixels_or_svgs():
    images = (
        '<img src="/img/diagrama.png" alt="Diagrama del sistema" width="800" height="400">'
        '<img src="https://cdn.x.test/foto.jpg" alt="Foto">'
        '<img src="/pixel.png" width="1" height="1">'
        '<img src="data:image/png;base64,AAAA">'
        '<img src="/logo.svg" alt="logo">'
    )

    doc = extract_html(article(images), "https://x.test/post/")

    assert doc.image_links == [
        ("Diagrama del sistema", "https://x.test/img/diagrama.png"),
        ("Foto", "https://cdn.x.test/foto.jpg"),
    ]
    assert "diagrama.png" not in doc.text  # the text sent to the model stays clean


def test_web_images_are_capped_at_five():
    images = "".join(f'<img src="/i/{n}.png" alt="i{n}">' for n in range(9))
    assert len(extract_html(article(images), "https://x.test/p").image_links) == 5


def test_figures_are_saved_in_the_vault_and_embedded_in_the_note(vault, cfg):
    doc = ExtractedDoc(
        "Arnés de agentes",
        "Los agentes de IA usan un arnés de código. " * 20 + "Anthropic publica ejemplos.",
        "paper",
        None,
        figures=[Figure(data=PNG + b"1", page=3, caption="Figure 2: El arnés y el modelo")],
        image_links=[("Esquema", "https://x.test/esquema.png")],
    )

    result = ingest(
        "x",
        vault=vault,
        llm=FakeLLM(make_plan()),
        cfg=cfg,
        extractor=lambda _: doc,
        today=date(2026, 9, 30),
    )

    saved = vault.root / "attachments" / "arnes-de-agentes" / "fig-1.png"
    assert saved.read_bytes() == PNG + b"1"
    body = vault.read_page(result.applied.source_path).body
    figures = body.split("## Figuras")[1].split("\n## ")[0]
    assert "![[attachments/arnes-de-agentes/fig-1.png|600]]" in figures
    assert "*Figure 2: El arnés y el modelo (p. 3)*" in figures
    assert "![Esquema](https://x.test/esquema.png)" in figures
