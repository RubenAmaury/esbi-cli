import io
import os
from email.message import EmailMessage
from pathlib import Path

import pytest
from PIL import Image

from esbi_cli.mail import convert
from esbi_cli.mail.convert import email_to_clip
from esbi_cli.vault import parse_page


def raw_email(
    *,
    subject="Notas sobre agentes",
    body="Cuerpo del correo. " * 10,
    html=None,
    sender="Ana <ana@x.test>",
    date="Mon, 29 Sep 2026 08:00:00 +0000",
    msgid="<abc123@x.test>",
    attachments=(),
    images=(),
) -> bytes:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["Date"], msg["Message-ID"] = subject, sender, date, msgid
    if body is not None:
        msg.set_content(body)
    if html is not None:
        if body is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    for name, data, mime in images:  # mime: "image/png", or anything, to lie about the type
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def test_a_plain_text_email_becomes_a_clip_note_with_its_metadata():
    clip = email_to_clip(raw_email())

    page = parse_page(Path(clip.filename), clip.content)
    assert clip.filename == "2026-09-29 Notas sobre agentes.md"
    assert page.meta["title"] == "Notas sobre agentes"
    assert page.meta["source"] == "mail:abc123@x.test"
    assert page.meta["kind"] == "email"
    assert page.meta["from"] == "Ana <ana@x.test>"
    assert page.meta["date"] == "2026-09-29"
    assert page.body.startswith("Cuerpo del correo.")


NEWSLETTER = (
    "<html><head><style>p{color:red}</style></head><body><script>alert(1)</script>"
    "<h1>Newsletter de agentes</h1>"
    "<p>Primer párrafo con <a href='https://x.test/a'>un enlace</a> y suficiente texto para "
    "que se considere contenido real del correo.</p>"
    "<p>Segundo párrafo que sigue hablando de arneses y herramientas de código.</p>"
    "</body></html>"
)


def test_an_html_only_newsletter_becomes_readable_text_without_markup_scripts_or_styles():
    clip = email_to_clip(raw_email(body=None, html=NEWSLETTER))

    body = parse_page(Path(clip.filename), clip.content).body
    assert "Primer párrafo" in body and "un enlace" in body and "Segundo párrafo" in body
    assert "alert(1)" not in body and "color:red" not in body and "<p>" not in body


def test_a_substantial_plain_part_wins_but_a_view_in_browser_stub_falls_back_to_html():
    rich = raw_email(html=NEWSLETTER)  # default plain body is a real 190-char text
    assert "Cuerpo del correo." in parse_page(Path("x"), email_to_clip(rich).content).body

    stub = raw_email(body="Ver este correo en el navegador", html=NEWSLETTER)
    assert "Primer párrafo" in parse_page(Path("x"), email_to_clip(stub).content).body


def test_attachments_are_ignored_and_encoded_headers_are_decoded():
    raw = raw_email(
        subject="Arnés de agentes: ¿qué es?",
        sender="José Pérez <jose@x.test>",
        attachments=[("secreto.pdf", b"%PDF-1.4 contenido binario del adjunto")],
    )

    clip = email_to_clip(raw)

    page = parse_page(Path(clip.filename), clip.content)
    assert page.meta["title"] == "Arnés de agentes: ¿qué es?"
    assert page.meta["from"] == "José Pérez <jose@x.test>"
    assert clip.filename == "2026-09-29 Arnés de agentes ¿qué es.md"
    assert "PDF" not in clip.content and "binario" not in clip.content


def test_an_email_without_date_or_message_id_still_converts_with_a_stable_source_id():
    msg = EmailMessage()
    msg["Subject"] = "Sin cabeceras"
    msg.set_content("Un texto suficientemente largo para ser una nota guardada. " * 3)
    raw = msg.as_bytes()

    first, second = email_to_clip(raw), email_to_clip(raw)

    meta = parse_page(Path(first.filename), first.content).meta
    assert meta["source"].startswith("mail:") and len(meta["source"]) > len("mail:")
    assert meta["source"] == parse_page(Path("x"), second.content).meta["source"]
    assert first.filename.endswith(" Sin cabeceras.md")


def test_newsletter_padding_made_of_invisible_characters_is_removed_from_the_text():
    padding = "\u034f\u200c \u00ad " * 40
    body = (
        f"Resumen del boletín sobre agentes.\n{padding}\n{padding}\n\nEl contenido real empieza aquí. "
        * 2
    )

    clip = email_to_clip(raw_email(body=body))

    text = parse_page(Path(clip.filename), clip.content).body
    assert "\u034f" not in text and "\u200c" not in text and "\u00ad" not in text
    assert "El contenido real empieza aquí." in text and "\n\n\n" not in text


def picture(fmt="PNG", side=300, noise=True) -> bytes:
    """A real image: random pixels do not compress, so it is well over the minimum size in bytes."""
    img = Image.frombytes(
        "RGB", (side, side), os.urandom(side * side * 3) if noise else bytes(side * side * 3)
    )
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def kept_images(clip):
    return [(name, data) for name, data in clip.images]


@pytest.mark.parametrize(
    "fmt, mime, suffix",
    [
        ("PNG", "image/png", ".png"),
        ("JPEG", "image/jpeg", ".jpg"),
        ("WEBP", "image/webp", ".webp"),
        ("TIFF", "image/tiff", ".tiff"),
    ],
)
def test_an_image_attachment_is_kept_with_the_extension_its_bytes_say(fmt, mime, suffix):
    data = picture(fmt)

    clip = email_to_clip(raw_email(images=[("captura", data, mime)]))

    assert [(Path(n).suffix, d) for n, d in clip.images] == [(suffix, data)]


def test_the_declared_type_and_the_file_name_are_not_trusted():
    png, gif = picture("PNG"), picture("GIF")
    mails = [
        ("a.png", b"not an image at all " * 400, "image/png"),  # declared image, bytes are not
        ("b.png", png, "application/octet-stream"),  # real image, declared as something else
        ("c.png", gif, "image/png"),  # a real image, but not one of the formats read
        ("d.png", b"%PDF-1.4 " + os.urandom(6000), "image/png"),
    ]
    clip = email_to_clip(raw_email(images=mails))

    assert clip.images == []


def test_an_attachment_name_with_path_parts_cannot_leave_the_inbox():
    data = picture()

    clip = email_to_clip(raw_email(images=[("../../etc/evil\\..\\x.png", data, "image/png")]))

    ((name, _),) = clip.images
    assert "/" not in name and "\\" not in name and ".." not in name


@pytest.mark.parametrize(
    "data",
    [
        picture(side=1),  # a tracking pixel
        picture(side=150),  # a small icon
        picture(noise=False),  # 300 x 300 but a few hundred bytes: a flat logo
    ],
    ids=["pixel", "icon", "flat"],
)
def test_pixels_logos_and_signature_images_are_not_kept(data):
    mail = raw_email(images=[("logo.png", data, "image/png")])

    assert email_to_clip(mail).images == []


def test_an_image_over_the_size_cap_is_dropped_and_the_total_per_mail_is_capped(monkeypatch):
    big, small = picture(side=400), picture(side=250)
    monkeypatch.setattr(convert, "MAX_IMAGE_BYTES", len(small) + 1)
    assert [
        n for n, _ in email_to_clip(raw_email(images=[("big.png", big, "image/png")])).images
    ] == []

    monkeypatch.setattr(convert, "MAX_MAIL_IMAGE_BYTES", len(small) * 2 + 1)
    three = [(f"p{i}.png", small, "image/png") for i in range(3)]
    assert len(email_to_clip(raw_email(images=three)).images) == 2


def test_a_mail_that_is_only_an_image_is_not_empty():
    clip = email_to_clip(raw_email(body=None, images=[("x.png", picture(), "image/png")]))

    assert clip.content == "" and len(clip.images) == 1


def test_links_in_the_text_are_collected_without_tracking_unsubscribe_or_pictures():
    body = (
        "Lee esto: https://blog.test/post-1, y tambien (https://blog.test/post-2). "
        "Otra vez https://blog.test/post-1\n"
        "Baja: https://news.test/unsubscribe?u=1 y https://news.test/email/preferences\n"
        "Ver en el navegador: https://news.test/view-in-browser/abc\n"
        "Pixel https://cdn.test/p.gif y https://click.news.test/r/abc123\n"
        "Correo mailto:ana@x.test y ftp://files.test/a\n"
        "Relleno de texto para llegar al minimo del cuerpo del correo. " * 3
    )

    clip = email_to_clip(raw_email(body=body))

    assert clip.links == ["https://blog.test/post-1", "https://blog.test/post-2"]
