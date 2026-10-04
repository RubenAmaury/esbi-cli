"""Images and scanned PDFs are read with an OCR model (a fake one here: no model, no network)."""

import io
from datetime import date
from functools import partial

import pymupdf
import pytest
from conftest import FakeLLM, FakeOCR, make_plan
from PIL import Image
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli.cli import app
from esbi_cli.config import load_config
from esbi_cli.extract import ExtractError, extract_source
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.llm.adapter import LLMError
from esbi_cli.mail.fetch import _remember_mail_file
from esbi_cli.queue import Queue
from esbi_cli.reingest import reingest_all

TEXT = "Los agentes de IA usan un arnés de código para planificar. " * 3  # well over 40 chars


def image_bytes(fmt="PNG", size=(120, 80), exif_orientation=None) -> bytes:
    img, out = Image.new("RGB", size, "white"), io.BytesIO()
    exif = Image.Exif()
    if exif_orientation:
        exif[0x0112] = exif_orientation
    img.save(out, fmt, exif=exif)
    return out.getvalue()


def scanned_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=image_bytes())
    return doc.tobytes()


def sent_size(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


@pytest.mark.parametrize("name, fmt", [("a.png", "PNG"), ("b.jpg", "JPEG"), ("c.webp", "WEBP")])
def test_an_image_becomes_a_source_whose_text_is_what_the_ocr_model_read(tmp_path, name, fmt):
    path = tmp_path / name
    path.write_bytes(image_bytes(fmt))

    doc = extract_source(str(path), ocr=FakeOCR(TEXT))

    assert doc.text == TEXT.strip() and doc.kind == "article" and doc.url is None
    assert doc.image_bytes == path.read_bytes() and doc.image_suffix == path.suffix
    assert len(doc.figures) == 1  # the note shows the image


def test_a_photo_is_turned_upright_and_shrunk_before_the_model_sees_it(tmp_path):
    big_sideways = tmp_path / "photo.jpg"
    big_sideways.write_bytes(image_bytes("JPEG", size=(4000, 3000), exif_orientation=6))
    ocr = FakeOCR(TEXT)

    extract_source(str(big_sideways), ocr=ocr)

    assert sent_size(ocr.images[0]) == (1200, 1600)  # EXIF said "rotate 90"; long side clamped


def test_an_image_with_almost_no_text_is_reported_instead_of_making_a_hollow_note(tmp_path):
    path = tmp_path / "landscape.jpg"
    path.write_bytes(image_bytes("JPEG"))

    with pytest.raises(ExtractError, match="no readable text"):
        extract_source(str(path), ocr=FakeOCR("[img]"))


def test_without_an_ocr_model_an_image_says_how_to_turn_it_on(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(image_bytes())

    with pytest.raises(ExtractError, match=r"\[llm\.ocr\]"):
        extract_source(str(path))


def test_a_file_that_is_not_an_image_is_an_error_not_an_empty_note(tmp_path):
    path = tmp_path / "fake.png"
    path.write_bytes(b"not an image")

    with pytest.raises(ExtractError, match="Could not open"):
        extract_source(str(path), ocr=FakeOCR(TEXT))


def test_an_ocr_model_that_is_down_fails_that_source_only(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(image_bytes())

    with pytest.raises(ExtractError, match="OCR model"):
        extract_source(str(path), ocr=FakeOCR(LLMError("http://localhost:11434 unreachable")))


def test_a_scanned_pdf_is_read_page_by_page_up_to_the_page_limit_and_says_so():
    ocr = FakeOCR("Página uno. " * 20, "Página dos. " * 20)

    doc = extract_pdf_bytes(scanned_pdf(3), "escaneado", ocr=ocr, max_ocr_pages=2)

    assert len(ocr.images) == 2
    assert doc.text.index("Página uno") < doc.text.index("Página dos")
    assert doc.kind == "paper" and doc.pdf_bytes and doc.figures == []
    assert any("2 of 3" in w for w in doc.warnings)  # the cap is never silent


def test_a_scanned_pdf_within_the_limit_has_no_warning():
    doc = extract_pdf_bytes(scanned_pdf(1), "x", ocr=FakeOCR(TEXT), max_ocr_pages=2)

    assert doc.warnings == []


def test_a_huge_pdf_page_is_rendered_no_larger_than_the_clamp():
    doc = pymupdf.open()
    doc.new_page(width=4000, height=3000).insert_image(
        pymupdf.Rect(0, 0, 4000, 3000), stream=image_bytes()
    )
    ocr = FakeOCR(TEXT)

    extract_pdf_bytes(doc.tobytes(), "x", ocr=ocr)

    assert max(sent_size(ocr.images[0])) <= 1600


def test_a_scanned_pdf_without_an_ocr_model_is_still_rejected_and_says_how_to_enable_it():
    with pytest.raises(ExtractError, match=r"\[llm\.ocr\]"):
        extract_pdf_bytes(scanned_pdf(1), "x")


def test_a_scanned_pdf_whose_pages_hold_no_text_is_rejected():
    with pytest.raises(ExtractError, match="no readable text"):
        extract_pdf_bytes(scanned_pdf(2), "x", ocr=FakeOCR("", "[img]"))


def test_a_pdf_with_a_text_layer_never_calls_the_ocr_model():
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 750), TEXT * 4, fontsize=11)

    out = extract_pdf_bytes(doc.tobytes(), "x", ocr=FakeOCR())  # an empty fake raises if asked

    assert "arnés" in out.text


def test_reingest_rebuilds_an_image_note_from_its_saved_text_and_keeps_the_picture(
    vault, cfg, tmp_path
):
    path = tmp_path / "Pizarra.png"
    path.write_bytes(image_bytes())
    ingest(
        str(path),
        vault=vault,
        llm=FakeLLM(make_plan()),
        cfg=cfg,
        extractor=partial(extract_source, ocr=FakeOCR(TEXT)),
        today=date(2026, 10, 2),
    )

    result = reingest_all(
        vault, FakeLLM(make_plan()), None, cfg, today=date(2026, 10, 3), all_sources=True
    )  # no OCR model: the text read the first time is in raw/

    assert result.done == ["Arnés de agentes"] and result.skipped == [] and result.failed == []
    body = vault.read_page(vault.page_path("sources", "Arnés de agentes")).body
    assert "![[attachments/arnes-de-agentes/fig-1.png|600]]" in body


def test_reingest_rebuilds_a_scanned_pdf_from_its_saved_text(vault, cfg):
    ingest(
        "x",
        vault=vault,
        llm=FakeLLM(make_plan()),
        cfg=cfg,
        extractor=lambda _: extract_pdf_bytes(scanned_pdf(1), "Escaneado", ocr=FakeOCR(TEXT)),
        today=date(2026, 10, 2),
    )

    result = reingest_all(
        vault, FakeLLM(make_plan()), None, cfg, today=date(2026, 10, 3), all_sources=True
    )

    assert result.done == ["Arnés de agentes"] and result.skipped == []


def test_a_scanned_pdf_from_a_mail_stays_email_when_rebuilt_and_never_reaches_a_cloud_model(
    vault, cfg
):
    pdf = scanned_pdf(1)
    ingest(
        "x",
        vault=vault,
        llm=FakeLLM(make_plan()),
        cfg=cfg,
        extractor=lambda _: extract_pdf_bytes(pdf, "Escaneado", ocr=FakeOCR(TEXT)),
        today=date(2026, 10, 2),
    )
    _remember_mail_file(vault, pdf)  # it turns out the PDF came attached to an email
    cloud = FakeLLM(make_plan())
    cloud.sends_text_out = True

    result = reingest_all(vault, cloud, None, cfg, today=date(2026, 10, 3), all_sources=True)

    assert result.done == [] and "PrivacyError" in result.failed[0][1]
    assert cloud.calls == []  # the text was never offered to it


def test_the_text_read_from_a_scanned_mail_attachment_goes_only_to_the_private_model(vault, cfg):
    pdf = scanned_pdf(1)
    _remember_mail_file(vault, pdf)
    cloud, private = FakeLLM(), FakeLLM(make_plan())
    cloud.sends_text_out = True

    result = ingest(
        "x",
        vault=vault,
        llm=cloud,
        private_llm=private,
        cfg=cfg,
        extractor=lambda _: extract_pdf_bytes(pdf, "Escaneado", ocr=FakeOCR(TEXT)),
        today=date(2026, 10, 2),
    )

    assert result.doc.kind == "email" and cloud.calls == [] and len(private.calls) == 1


def test_an_ingested_image_is_kept_in_raw_and_shown_in_the_note(vault, cfg, tmp_path):
    path = tmp_path / "Pizarra.png"
    path.write_bytes(image_bytes())

    result = ingest(
        str(path),
        vault=vault,
        llm=FakeLLM(make_plan()),
        cfg=cfg,
        extractor=partial(extract_source, ocr=FakeOCR(TEXT)),
        today=date(2026, 10, 2),
    )

    note = vault.read_page(result.applied.source_path)
    kept = list((vault.root / "raw").glob("*.png"))
    assert len(kept) == 1 and kept[0].read_bytes() == path.read_bytes()  # original, immutable
    assert (
        (vault.root / note.meta["raw"]).read_text(encoding="utf-8").strip().endswith(TEXT.strip())
    )
    assert "![[attachments/arnes-de-agentes/fig-1.png|600]]" in note.body
    assert "(p. 0)" not in note.body  # an image has no page number


# --- the commands ---------------------------------------------------------------------------


@pytest.fixture
def ocr_config(config_file):
    config_file.write_text(
        config_file.read_text() + '\n[llm.ocr]\nmodel = "ollama/qwen3-vl:2b-instruct"\n'
    )
    return config_file


def sb(config, *args):
    return CliRunner().invoke(app, [*args, "--config", str(config)])


def test_scan_says_which_files_it_did_not_read_and_how_to_turn_ocr_on(vault, config_file):
    (vault.root / "inbox" / "Pizarra.png").write_bytes(image_bytes())
    (vault.root / "inbox" / "informe.docx").write_bytes(b"docx")

    result = sb(config_file, "scan")

    assert result.exit_code == 0 and "Queued 0" in result.stdout
    assert "Pizarra.png" in result.stdout and "informe.docx" in result.stdout
    assert "[llm.ocr]" in result.stdout  # an image is there and nothing can read it


def test_scan_does_not_mention_ocr_when_only_other_files_are_unsupported(vault, config_file):
    (vault.root / "inbox" / "informe.docx").write_bytes(b"docx")

    assert "[llm.ocr]" not in sb(config_file, "scan").stdout


def test_scan_queues_images_when_an_ocr_model_is_configured(vault, ocr_config):
    (vault.root / "inbox" / "Pizarra.png").write_bytes(image_bytes())

    result = sb(ocr_config, "scan")

    assert "Queued 1" in result.stdout and "not read" not in result.stdout
    assert (vault.root / "raw" / "inbox" / "Pizarra.png").exists()


def test_add_takes_an_image_only_when_an_ocr_model_is_configured(tmp_path, config_file, ocr_config):
    path = tmp_path / "foto.jpg"
    path.write_bytes(image_bytes("JPEG"))
    plain = tmp_path / "plain.toml"
    plain.write_text(config_file.read_text().split("[llm.ocr]")[0])

    refused = sb(plain, "add", str(path))
    queued = sb(ocr_config, "add", str(path))

    assert refused.exit_code == 1 and "[llm.ocr]" in refused.output
    assert queued.exit_code == 0 and "Queued 1" in queued.stdout


def test_run_reads_an_image_with_the_ocr_model_and_writes_its_note(vault, ocr_config, monkeypatch):
    ocr = FakeOCR(TEXT)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    monkeypatch.setattr(cli, "make_ocr", lambda _cfg: ocr)
    (vault.root / "inbox" / "Pizarra.png").write_bytes(image_bytes())

    run = sb(ocr_config, "run")

    assert run.exit_code == 0, run.output
    assert "ingested: 1" in run.stdout and len(ocr.images) == 1
    assert "(150 tokens)" in run.stdout  # the reading counts against the run's token budget
    assert vault.page_path("sources", "Arnés de agentes").exists()


def test_run_without_an_ocr_model_leaves_images_where_they_are_and_says_so(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    (vault.root / "inbox" / "Pizarra.png").write_bytes(image_bytes())

    run = sb(config_file, "run")

    assert run.exit_code == 0 and "Pizarra.png" in run.stdout and "[llm.ocr]" in run.stdout
    assert (vault.root / "inbox" / "Pizarra.png").exists()
    assert "queued: 0" in sb(config_file, "status").stdout


def test_run_reports_a_source_the_ocr_model_could_not_read_and_goes_on(
    vault, ocr_config, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    monkeypatch.setattr(cli, "make_ocr", lambda _cfg: FakeOCR("[img]"))
    (vault.root / "inbox" / "paisaje.jpg").write_bytes(image_bytes("JPEG"))

    run = sb(ocr_config, "run")

    assert run.exit_code == 0 and "failed: 1" in run.stdout
    [item] = Queue(vault.root / ".esbi" / "queue.sqlite3").items("queued")  # retried next run
    assert "no readable text" in item.error  # the queue keeps the reason, `sb status` shows it


def test_an_ocr_model_that_could_send_images_away_stops_the_run_before_anything_is_read(
    tmp_path, vault, config_file, monkeypatch
):
    bad = tmp_path / "bad.toml"
    bad.write_text(config_file.read_text() + '\n[llm.ocr]\nmodel = "openai/gpt-4o"\n')
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    (vault.root / "inbox" / "Pizarra.png").write_bytes(image_bytes())

    run = sb(bad, "run")

    assert run.exit_code == 1 and "[llm.ocr]" in run.output
    assert (vault.root / "inbox" / "Pizarra.png").exists()  # untouched


def test_ingest_reads_one_image_given_by_path(tmp_path, vault, ocr_config, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    monkeypatch.setattr(cli, "make_ocr", lambda _cfg: FakeOCR(TEXT))
    path = tmp_path / "Pizarra.png"
    path.write_bytes(image_bytes())

    result = sb(ocr_config, "ingest", str(path), "--no-commit")

    assert result.exit_code == 0, result.output
    assert "Ingested: Arnés de agentes" in result.stdout


def test_ingest_of_a_scanned_pdf_says_how_to_enable_ocr_when_it_is_off(
    tmp_path, vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    path = tmp_path / "scan.pdf"
    path.write_bytes(scanned_pdf(1))

    result = sb(config_file, "ingest", str(path))

    assert result.exit_code == 1 and "[llm.ocr]" in result.output


def init(tmp_path, *extra):
    config = tmp_path / "cfg" / "config.toml"
    args = ["init", "--vault", str(tmp_path / "Brain"), "--config-file", str(config), *extra]
    return CliRunner().invoke(app, args, input=None), config


def test_init_leaves_ocr_off_unless_asked(tmp_path):
    result, config = init(tmp_path, "--no-obsidian")

    assert result.exit_code == 0, result.output
    assert "ocr" not in load_config(config).llm and "ollama pull qwen3-vl" not in result.stdout


def test_init_ocr_writes_the_local_vision_model_and_says_what_to_pull(tmp_path):
    result, config = init(tmp_path, "--no-obsidian", "--ocr")

    assert result.exit_code == 0, result.output
    assert load_config(config).llm["ocr"].model == "ollama/qwen3-vl:2b-instruct"
    assert "ollama pull qwen3-vl:2b-instruct" in result.stdout


def test_init_ocr_needs_ollama_because_only_it_serves_images_here(tmp_path):
    result, config = init(
        tmp_path, "--no-obsidian", "--ocr", "--runtime", "lmstudio", "--local-model", "m"
    )

    assert result.exit_code == 1 and "Ollama" in result.output and not config.exists()
