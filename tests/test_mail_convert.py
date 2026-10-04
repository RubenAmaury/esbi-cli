from email.message import EmailMessage
from pathlib import Path

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
