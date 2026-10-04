"""Figures: real images from PDFs (copied into the vault) and linked images from web pages."""

from datetime import date

import pymupdf
from conftest import FakeLLM, make_plan

from esbi_cli.extract import ExtractedDoc, Figure
from esbi_cli.extract.html import extract_html
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.ingest.pipeline import ingest

PNG = b"\x89PNG\r\n\x1a\n"
BODY = "Texto del artículo sobre agentes de código y su verificación. " * 30


def png(w, h, shade):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(shade)
    return pix.tobytes("png")


def make_pdf(pages):
    """`pages`: one list per page of (rect, png bytes, caption or None)."""
    doc = pymupdf.open()
    for figures in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 500, 550, 780), BODY, fontsize=9)
        for rect, data, caption in figures:
            page.insert_image(rect, stream=data)
            if caption:
                page.insert_text((rect.x0, rect.y1 + 14), caption, fontsize=10)
    return doc.tobytes()


def test_figures_are_extracted_as_png_with_their_caption_and_icons_are_skipped():
    figure = (
        pymupdf.Rect(72, 60, 372, 260),
        png(300, 200, 150),
        "Figure 1: Arquitectura del arnés",
    )
    icon = (pymupdf.Rect(400, 60, 430, 90), png(30, 30, 90), None)

    doc = extract_pdf_bytes(make_pdf([[figure, icon]]), "paper")

    assert len(doc.figures) == 1
    fig = doc.figures[0]
    assert fig.page == 1 and fig.data.startswith(PNG)
    assert fig.caption.startswith("Figure 1") and "arnés" in fig.caption


def test_a_pdf_without_images_has_no_figures_and_the_same_image_is_kept_once():
    assert extract_pdf_bytes(make_pdf([[]]), "paper").figures == []

    same = png(300, 200, 120)
    twice = [
        [(pymupdf.Rect(72, 60, 372, 260), same, None)],
        [(pymupdf.Rect(72, 60, 372, 260), same, None)],
    ]
    assert len(extract_pdf_bytes(make_pdf(twice), "paper").figures) == 1


def test_at_most_eight_figures_are_kept_captioned_ones_first_then_the_biggest():
    pages = [  # pages 1-3: small but captioned; pages 4-12: bigger, no caption
        [(pymupdf.Rect(72, 60, 272, 210), png(200, 150, 10 + n), f"Figure {n}: algo importante")]
        for n in range(1, 4)
    ] + [[(pymupdf.Rect(72, 60, 422, 300), png(350, 240, 60 + n), None)] for n in range(4, 13)]

    figures = extract_pdf_bytes(make_pdf(pages), "paper").figures

    assert len(figures) == 8
    assert {1, 2, 3} <= {f.page for f in figures}  # every captioned figure made it
    assert [f.page for f in figures] == sorted(f.page for f in figures)  # in reading order


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
