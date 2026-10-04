from conftest import FakeMailClient
from test_mail_convert import raw_email

from esbi_cli.mail.fetch import fetch_mail


def inbox_files(vault):
    return sorted(p.name for p in (vault.root / "inbox").glob("*.md"))


def test_recent_mail_is_saved_to_the_inbox_and_marked_seen_only_after_it_is_written(vault):
    def assert_written(uid):
        assert any(f.startswith("2026-09-29") for f in inbox_files(vault)), "marked before saving"

    client = FakeMailClient(
        ("1", raw_email(subject="Primero", msgid="<a@x.test>")),
        ("2", raw_email(subject="Segundo", msgid="<b@x.test>")),
        on_mark=assert_written,
    )

    result = fetch_mail(client, vault)

    assert (result.saved, result.duplicates, result.failed) == (2, 0, 0)
    assert inbox_files(vault) == ["2026-09-29 Primero.md", "2026-09-29 Segundo.md"]
    assert client.seen == ["1", "2"]


def test_two_mails_with_the_same_subject_and_day_do_not_overwrite_each_other(vault):
    client = FakeMailClient(
        ("1", raw_email(subject="Igual", msgid="<a@x.test>")),
        ("2", raw_email(subject="Igual", msgid="<b@x.test>")),
    )

    result = fetch_mail(client, vault)

    assert result.saved == 2
    assert inbox_files(vault) == ["2026-09-29 Igual (2).md", "2026-09-29 Igual.md"]


def test_a_message_id_already_captured_is_marked_seen_but_not_saved_again(vault):
    fetch_mail(FakeMailClient(("1", raw_email(msgid="<a@x.test>"))), vault)
    # the worker's inbox scan moves clips to raw/inbox; the copy must still count as known
    (vault.root / "raw" / "inbox").mkdir(parents=True)
    for clip in (vault.root / "inbox").glob("*.md"):
        clip.rename(vault.root / "raw" / "inbox" / clip.name)

    forwarded_again = FakeMailClient(("9", raw_email(msgid="<a@x.test>")))
    result = fetch_mail(forwarded_again, vault)

    assert (result.saved, result.duplicates) == (0, 1)
    assert inbox_files(vault) == [] and forwarded_again.seen == ["9"]


def test_a_broken_mail_is_reported_once_and_does_not_stop_the_others(vault):
    client = FakeMailClient(
        ("1", raw_email(subject="Vacío", body="", msgid="<a@x.test>")),
        ("2", raw_email(subject="Bueno", msgid="<b@x.test>")),
    )

    first = fetch_mail(client, vault)
    second = fetch_mail(client, vault)  # the window still contains both mails

    assert (first.saved, first.failed) == (1, 1)
    assert client.seen[0] == "2" and inbox_files(vault) == ["2026-09-29 Bueno.md"]
    assert (second.saved, second.duplicates, second.failed) == (0, 1, 0)  # no repeated complaint


def test_mail_you_opened_in_gmail_is_still_collected_because_the_window_ignores_seen_state(vault):
    client = FakeMailClient(("1", raw_email(msgid="<a@x.test>")))
    client.seen.append("1")  # opened by you before the worker came

    assert fetch_mail(client, vault).saved == 1


def test_a_pdf_attachment_is_saved_in_the_inbox_once_even_if_the_mail_is_fetched_again(vault):
    pdf = b"%PDF-1.4 un adjunto de prueba"
    mail = raw_email(msgid="<a@x.test>", attachments=[("Informe.pdf", pdf)])
    client = FakeMailClient(("1", mail))

    fetch_mail(client, vault)
    fetch_mail(client, vault)

    pdfs = sorted(p.name for p in (vault.root / "inbox").glob("*.pdf"))
    assert pdfs == ["2026-09-29 Notas sobre agentes - Informe.pdf"]
    assert (vault.root / "inbox" / pdfs[0]).read_bytes() == pdf


def test_a_mail_that_is_only_a_pdf_still_yields_the_pdf(vault):
    mail = raw_email(
        subject="Para leer", body=None, msgid="<a@x.test>", attachments=[("P.pdf", b"%PDF-1.4 x")]
    )

    result = fetch_mail(FakeMailClient(("1", mail)), vault)

    assert (result.saved, result.failed) == (1, 0)
    assert inbox_files(vault) == [] and len(list((vault.root / "inbox").glob("*.pdf"))) == 1


def test_an_image_attachment_is_saved_next_to_the_mail_once_and_remembered_as_email(vault):
    from test_mail_convert import picture

    from esbi_cli.mail.fetch import is_mail_file

    png = picture()
    mail = raw_email(msgid="<a@x.test>", images=[("Captura.png", png, "image/png")])
    client = FakeMailClient(("1", mail))

    first = fetch_mail(client, vault)
    fetch_mail(client, vault)

    images = sorted(p.name for p in (vault.root / "inbox").glob("*.png"))
    assert images == ["2026-09-29 Notas sobre agentes - Captura.png"]
    assert (vault.root / "inbox" / images[0]).read_bytes() == png
    assert first.images == 1 and is_mail_file(vault, png)


def test_the_same_image_in_two_mails_is_kept_once(vault):
    from test_mail_convert import picture

    png = picture()
    client = FakeMailClient(
        ("1", raw_email(msgid="<a@x.test>", images=[("A.png", png, "image/png")])),
        ("2", raw_email(msgid="<b@x.test>", images=[("B.png", png, "image/png")])),
    )

    result = fetch_mail(client, vault)

    assert len(list((vault.root / "inbox").glob("*.png"))) == 1 and result.images == 1


def test_a_mail_that_is_only_an_image_yields_the_image(vault):
    from test_mail_convert import picture

    mail = raw_email(
        body=None, msgid="<a@x.test>", images=[("P.jpg", picture("JPEG"), "image/jpeg")]
    )

    result = fetch_mail(FakeMailClient(("1", mail)), vault)

    assert (result.saved, result.failed, result.images) == (1, 0, 1)
    assert inbox_files(vault) == [] and len(list((vault.root / "inbox").glob("*.jpg"))) == 1


LINKED = (
    "Mira estos dos: https://blog.test/uno y https://blog.test/dos . "
    "Y tambien https://blog.test/tres https://blog.test/cuatro. Relleno para el cuerpo. " * 2
)


def queued(queue):
    return [(i.target, i.origin) for i in queue.items("queued")]


def test_links_are_ignored_unless_following_is_switched_on(vault, queue):
    fetch_mail(FakeMailClient(("1", raw_email(body=LINKED, msgid="<a@x.test>"))), vault, queue)

    assert queued(queue) == []


def test_followed_links_are_queued_as_email_derived_up_to_the_cap_and_never_fetched_here(
    vault, queue, monkeypatch
):
    def no_network(*args, **kwargs):
        raise AssertionError("a link must only be queued at capture time, never fetched")

    monkeypatch.setattr("esbi_cli.netguard.safe_get", no_network)
    monkeypatch.setattr("esbi_cli.extract.safe_get", no_network)

    result = fetch_mail(
        FakeMailClient(("1", raw_email(body=LINKED, msgid="<a@x.test>"))),
        vault,
        queue,
        follow_links=True,
        max_links=3,
    )

    assert queued(queue) == [
        ("https://blog.test/uno", "mail-link"),
        ("https://blog.test/dos", "mail-link"),
        ("https://blog.test/tres", "mail-link"),
    ]
    assert result.links == 3


def test_a_link_already_queued_or_already_a_source_is_not_queued_again(vault, queue):
    from conftest import add_source

    queue.add("https://blog.test/uno", origin="legacy")
    read = add_source(vault, "Ya leído")
    read.meta["url"] = "https://blog.test/dos"
    vault.write_page(read)

    result = fetch_mail(
        FakeMailClient(("1", raw_email(body=LINKED, msgid="<a@x.test>"))),
        vault,
        queue,
        follow_links=True,
        max_links=3,
    )

    assert [t for t, _ in queued(queue)] == [
        "https://blog.test/uno",
        "https://blog.test/tres",
        "https://blog.test/cuatro",
    ]
    assert result.links == 2 and queue.get("https://blog.test/uno").origin == "legacy"


def test_a_mail_fetched_again_does_not_queue_its_links_again(vault, queue):
    client = FakeMailClient(("1", raw_email(body=LINKED, msgid="<a@x.test>")))

    first = fetch_mail(client, vault, queue, follow_links=True)
    second = fetch_mail(client, vault, queue, follow_links=True)

    assert (first.links, second.links) == (3, 0)
