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
