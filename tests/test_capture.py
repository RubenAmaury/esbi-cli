from datetime import date

from esbi_cli.capture.inbox import scan_inbox
from esbi_cli.capture.legacy import import_legacy


def test_scan_inbox_queues_dropped_pdfs_and_moves_them_out_of_the_inbox(vault, queue):
    (vault.root / "inbox" / "Paper.pdf").write_bytes(b"%PDF-1.4 fake")

    result = scan_inbox(vault, queue)

    moved = vault.root / "raw" / "inbox" / "Paper.pdf"
    assert not (vault.root / "inbox" / "Paper.pdf").exists()
    assert moved.read_bytes() == b"%PDF-1.4 fake"
    assert [i.target for i in queue.claim(5)] == [str(moved)]
    assert result.enqueued == 1


def test_scan_inbox_queues_web_clipper_notes_and_leaves_other_files_alone(vault, queue):
    clip = "---\nsource: https://x.test/p\ntitle: Un post\n---\nContenido clipeado"
    (vault.root / "inbox" / "Un post.md").write_text(clip, encoding="utf-8")
    (vault.root / "inbox" / ".gitkeep").write_text("")
    (vault.root / "inbox" / "photo.png").write_bytes(b"png")

    result = scan_inbox(vault, queue)

    moved = vault.root / "raw" / "inbox" / "Un post.md"
    assert moved.read_text(encoding="utf-8") == clip
    assert [i.target for i in queue.claim(5)] == [str(moved)]
    assert result.enqueued == 1
    assert (vault.root / "inbox" / "photo.png").exists()
    assert (vault.root / "inbox" / ".gitkeep").exists()


def test_scan_inbox_queues_images_only_when_an_ocr_model_can_read_them(vault, queue):
    (vault.root / "inbox" / "Pizarra.PNG").write_bytes(b"png")

    off = scan_inbox(vault, queue)

    assert off.enqueued == 0 and off.unsupported == ["Pizarra.PNG"]  # said, not ignored
    assert (vault.root / "inbox" / "Pizarra.PNG").exists()

    on = scan_inbox(vault, queue, images=True)

    moved = vault.root / "raw" / "inbox" / "Pizarra.PNG"
    assert moved.read_bytes() == b"png" and not (vault.root / "inbox" / "Pizarra.PNG").exists()
    assert [(i.target, i.label) for i in queue.claim(5)] == [(str(moved), "Pizarra")]
    assert on.enqueued == 1 and on.unsupported == []


def test_scan_inbox_reports_every_file_it_cannot_read_but_not_hidden_files_or_folders(vault, queue):
    inbox = vault.root / "inbox"
    (inbox / "informe.docx").write_bytes(b"docx")
    (inbox / "foto.heic").write_bytes(b"heic")
    (inbox / ".DS_Store").write_bytes(b"")
    (inbox / "carpeta").mkdir()

    result = scan_inbox(vault, queue, images=True)

    assert result.unsupported == ["foto.heic", "informe.docx"]


def test_the_same_image_dropped_twice_is_a_duplicate(vault, queue):
    (vault.root / "inbox" / "a.png").write_bytes(b"png")
    scan_inbox(vault, queue, images=True)
    (vault.root / "inbox" / "b.png").write_bytes(b"png")

    again = scan_inbox(vault, queue, images=True)

    assert again.duplicates == 1 and again.enqueued == 0
    assert not (vault.root / "inbox" / "b.png").exists()


def _snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_import_legacy_queues_links_and_pdfs_oldest_first_and_is_rerunnable(tmp_path, queue):
    old = tmp_path / "old-notes"
    (old / "Links").mkdir(parents=True)
    (old / "PDFs").mkdir()
    (old / "Links" / "04-09-2026.md").write_text("[https://a.test/x]\n")
    (old / "Links" / "31-08-2026.md").write_text(
        "[https://a.test/x?utm_source=share]\n[https://lnkd.in/p/ej99YcyK]\n\n"
        "una nota suelta\nhttps://b.test/plain\n"
    )
    (old / "PDFs" / "Paper.pdf").write_bytes(b"%PDF fake")
    (old / "PDFs" / "notes.txt").write_text("not a pdf")
    before = _snapshot(old)

    first = import_legacy(old, queue)

    assert (first.added, first.duplicates) == (4, 1)
    assert [i.target for i in queue.claim(10)] == [
        "https://a.test/x",
        "https://lnkd.in/p/ej99YcyK",
        "https://b.test/plain",
        str((old / "PDFs" / "Paper.pdf").resolve()),
    ]
    assert import_legacy(old, queue).added == 0
    assert _snapshot(old) == before


def test_legacy_links_keep_the_date_of_the_file_they_were_saved_in_and_pdfs_are_labelled(
    tmp_path, queue
):
    old = tmp_path / "old-notes"
    (old / "Links").mkdir(parents=True)
    (old / "PDFs").mkdir()
    (old / "Links" / "31-08-2026.md").write_text("[https://a.test/x]\nhttps://b.test/plain\n")
    (old / "Links" / "04-09-2026.md").write_text("[https://a.test/x]\n[https://c.test/later]\n")
    (old / "Links" / "notas.md").write_text("[https://d.test/undated]\n")
    (old / "PDFs" / "Mi Paper.pdf").write_bytes(b"%PDF fake")

    import_legacy(old, queue)

    assert queue.get("https://a.test/x").captured == date(2026, 8, 31)  # the first save wins
    assert queue.get("https://b.test/plain").captured == date(2026, 8, 31)
    assert queue.get("https://c.test/later").captured == date(2026, 9, 4)
    assert queue.get("https://d.test/undated").captured is None
    pdf = queue.get(str((old / "PDFs" / "Mi Paper.pdf").resolve()))
    assert (pdf.captured, pdf.label) == (None, "Mi Paper")


def test_inbox_items_are_labelled_with_the_clip_title_or_the_file_name(vault, queue):
    (vault.root / "inbox" / "clip-1234.md").write_text(
        "---\nsource: https://x.test/p\ntitle: Un gran post\n---\n" + "x" * 60
    )
    (vault.root / "inbox" / "Sin titulo.md").write_text("Una nota suelta sin frontmatter " * 3)
    (vault.root / "inbox" / "Paper Final.pdf").write_bytes(b"%PDF fake")

    scan_inbox(vault, queue)

    label = lambda name: queue.get(str(vault.root / "raw" / "inbox" / name)).label  # noqa: E731
    assert label("clip-1234.md") == "Un gran post"
    assert label("Sin titulo.md") == "Sin titulo"
    assert label("Paper Final.pdf") == "Paper Final"


def test_two_files_with_the_same_name_never_overwrite_each_other(vault, queue):
    """Found by testing: the second file replaced the first in raw/ and was never queued."""
    inbox, raw = vault.root / "inbox", vault.root / "raw" / "inbox"
    (inbox / "paper.pdf").write_bytes(b"%PDF first paper")
    scan_inbox(vault, queue)
    (inbox / "paper.pdf").write_bytes(b"%PDF a different paper, same file name")

    result = scan_inbox(vault, queue)

    assert (raw / "paper.pdf").read_bytes() == b"%PDF first paper"  # raw/ is immutable
    assert (raw / "paper (2).pdf").read_bytes() == b"%PDF a different paper, same file name"
    assert result.enqueued == 1 and queue.counts() == {"queued": 2}


def test_the_same_file_dropped_again_is_recognised_as_a_duplicate(vault, queue):
    inbox = vault.root / "inbox"
    (inbox / "paper.pdf").write_bytes(b"%PDF same bytes")
    scan_inbox(vault, queue)
    (inbox / "paper.pdf").write_bytes(b"%PDF same bytes")

    result = scan_inbox(vault, queue)

    assert (result.enqueued, result.duplicates) == (0, 1)
    assert not (inbox / "paper.pdf").exists()  # the redundant copy is cleared from the inbox
    assert sorted(p.name for p in (vault.root / "raw" / "inbox").iterdir()) == ["paper.pdf"]
    assert queue.counts() == {"queued": 1}


def test_a_copy_is_a_duplicate_whatever_its_name_and_whichever_earlier_version_it_matches(
    vault, queue
):
    inbox, raw = vault.root / "inbox", vault.root / "raw" / "inbox"
    (inbox / "paper.pdf").write_bytes(b"%PDF one")
    scan_inbox(vault, queue)
    (inbox / "paper.pdf").write_bytes(b"%PDF two")
    scan_inbox(vault, queue)  # kept as "paper (2).pdf"

    (inbox / "paper.pdf").write_bytes(b"%PDF two")  # again the second version
    (inbox / "Copy of the paper.pdf").write_bytes(b"%PDF one")  # a renamed copy of the first
    result = scan_inbox(vault, queue)

    assert (result.enqueued, result.duplicates) == (0, 2)
    assert sorted(p.name for p in raw.iterdir()) == ["paper (2).pdf", "paper.pdf"]
    assert queue.counts() == {"queued": 2}
