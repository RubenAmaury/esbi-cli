from dataclasses import replace
from datetime import date, datetime

from conftest import add_source

from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.report.readstate import sync_read_state
from esbi_cli.runlog import RunLog, RunRecord
from esbi_cli.vault import Page, Vault

TODAY = date(2026, 9, 29)


def sections(text: str) -> dict[str, list[str]]:
    """Note body as {heading: non-empty lines}, so tests read like the note does."""
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        elif current and line.strip():
            out[current].append(line)
    return out


def build(vault, queue, day=TODAY):
    return sections(build_daily_index(vault, queue, day).read_text(encoding="utf-8"))


def test_processed_today_lists_todays_sources_as_checkboxes_that_reflect_read_state(vault, queue):
    add_source(vault, "Nueva", summary="Sobre agentes.")
    add_source(vault, "Ya marcada", status="read", read="2026-09-29")
    add_source(vault, "De ayer", processed="2026-09-28")

    path = build_daily_index(vault, queue, TODAY)

    assert path == vault.wiki / "daily" / "2026-09-29.md"
    assert sections(path.read_text(encoding="utf-8"))["Procesado hoy"] == [
        "- [ ] [[Nueva]] — Sobre agentes.",
        "- [x] [[Ya marcada]] — Resumen de prueba de la fuente.",
    ]


def test_read_section_lists_sources_marked_read_today_and_says_so_when_none(vault, queue):
    assert build(vault, queue)["Leído"] == ["_Nada nuevo marcado como leído._"]

    add_source(vault, "Leída hoy", status="read", read="2026-09-29", processed="2026-09-27")
    add_source(vault, "Leída antes", status="read", read="2026-09-28", processed="2026-09-27")

    assert build(vault, queue)["Leído"] == ["- [[Leída hoy]] — Resumen de prueba de la fuente."]


def test_tomorrows_queue_shows_count_and_oldest_items_with_short_names_for_files(
    vault, queue, tmp_path
):
    assert build(vault, queue)["Cola de mañana"] == ["_La cola está vacía._"]

    queue.add("https://x.test/a", origin="inbox")
    queue.add(str(tmp_path / "Paper.pdf"), origin="inbox")
    assert build(vault, queue)["Cola de mañana"] == [
        "2 fuentes en cola.",
        "- https://x.test/a",
        "- Paper.pdf",
    ]

    for n in range(25):
        queue.add(f"https://x.test/more/{n}", origin="inbox")
    lines = build(vault, queue)["Cola de mañana"]
    assert lines[0] == "27 fuentes en cola (se muestran las 20 más antiguas)."
    assert len(lines) == 21


def test_review_section_lists_review_notes_and_parked_failures(vault, queue):
    assert build(vault, queue)["Por revisar"] == ["_Nada pendiente._"]

    (vault.wiki / "review" / "2026-09-28 contradicción - Fuente X.md").write_text("nota")
    (vault.wiki / "review" / ".gitkeep").write_text("")
    queue.add("https://bad.test/x", origin="inbox")
    for _ in range(3):
        queue.fail(queue.claim(1)[0].id, "ExtractError: nada legible")

    assert build(vault, queue)["Por revisar"] == [
        "- [[2026-09-28 contradicción - Fuente X]]",
        "- No se pudo procesar https://bad.test/x (ExtractError: nada legible)",
    ]


def test_revisit_section_picks_three_older_pages_and_rotates_from_day_to_day(vault, queue):
    assert build(vault, queue)["Repasar"] == ["_Todavía no hay notas antiguas para repasar._"]

    for i in range(6):
        add_source(vault, f"Vieja {i}", processed="2026-09-01")
    add_source(vault, "Nueva hoy")

    day1 = build(vault, queue, date(2026, 9, 29))["Repasar"]
    day2 = build(vault, queue, date(2026, 9, 30))["Repasar"]

    assert len(day1) == 3 and len(day2) == 3 and day1 != day2
    assert all(line.startswith("- [[Vieja ") for line in day1)  # today's own source is excluded


def test_stats_count_pages_todays_activity_read_progress_and_orphans(vault, queue):
    add_source(vault, "Fuente A", body="# A\n\n## Conceptos\n- [[Concepto 1]]")
    add_source(vault, "Fuente B", status="read", read="2026-09-29", processed="2026-09-28")
    vault.write_page(
        Page(
            vault.page_path("concepts", "Concepto 1"),
            {"title": "Concepto 1", "updated": "2026-09-29", "summary": "x"},
            "# Concepto 1\n\n## Desde [[Fuente A]]\ntexto",
        )
    )

    assert build(vault, queue)["Estadísticas"] == [
        "- Páginas: 3 (fuentes: 2, conceptos: 1, entidades: 0)",
        "- Hoy: 1 fuentes procesadas, 1 conceptos/entidades actualizados",
        "- Leídas: 1 de 2 fuentes",
        "- Huérfanas (sin enlaces entrantes): 1",
    ]


def test_a_tick_made_in_the_note_survives_regeneration_and_is_reported_as_read(vault, queue):
    add_source(vault, "Nueva")
    note = build_daily_index(vault, queue, TODAY)

    note.write_text(note.read_text(encoding="utf-8").replace("- [ ] [[Nueva]]", "- [x] [[Nueva]]"))
    sync_read_state(vault, TODAY)
    rebuilt = build(vault, queue)

    assert rebuilt["Procesado hoy"][0].startswith("- [x] [[Nueva]]")
    assert rebuilt["Leído"][0].startswith("- [[Nueva]]")


def test_home_gets_a_managed_block_for_todays_index_and_keeps_the_rest_of_the_page(vault, queue):
    home = vault.root / "Home.md"
    home.write_text("# esbi-cli\n\nMis notas propias.\n", encoding="utf-8")
    add_source(vault, "Sin leer A")
    queue.add("https://x.test/a", origin="inbox")

    build_daily_index(vault, queue, TODAY)
    first = home.read_text(encoding="utf-8")

    assert "Mis notas propias." in first
    assert "- Índice de hoy: [[2026-09-29]]" in first
    assert "- Sin leer: 1 fuentes" in first and "- En cola: 1 fuentes" in first

    build_daily_index(vault, queue, date(2026, 9, 30))
    second = home.read_text(encoding="utf-8")
    assert second.count("esbi:start") == 1
    assert "[[2026-09-30]]" in second and "[[2026-09-29]]" not in second
    assert "Mis notas propias." in second


def test_home_is_created_when_missing(vault, queue):
    build_daily_index(vault, queue, TODAY)
    assert "[[2026-09-29]]" in (vault.root / "Home.md").read_text(encoding="utf-8")


def test_runs_section_lists_todays_runs_with_counts_and_why_they_stopped(vault, queue):
    assert build(vault, queue)["Ejecuciones"] == ["_Todavía no hubo ejecuciones hoy._"]

    night = RunRecord(
        started=datetime(2026, 9, 29, 3, 5),
        finished=datetime(2026, 9, 29, 3, 9, 30),
        ingested=6,
        skipped=1,
        failed=0,
        tokens_used=39711,
        stopped_by="max_sources",
        trigger="scheduled",
    )
    outage = replace(
        night,
        started=datetime(2026, 9, 29, 9, 0),
        finished=datetime(2026, 9, 29, 9, 0, 2),
        ingested=0,
        skipped=0,
        tokens_used=0,
        stopped_by="llm_unavailable",
    )
    manual = replace(
        night,
        started=datetime(2026, 9, 29, 10, 0),
        finished=datetime(2026, 9, 29, 10, 4, 30),
        stopped_by=None,
        trigger="manual",
    )
    yesterday = replace(night, started=datetime(2026, 9, 28, 3, 5))
    log = RunLog(vault.root / ".esbi" / "runs.jsonl")
    for run in (yesterday, night, outage, manual):
        log.record(run)

    assert build(vault, queue)["Ejecuciones"] == [
        "- 03:05 — procesadas: 6, omitidas: 1, fallidas: 0 · 39711 tokens · 4 min"
        " · detenida: límite de fuentes",
        "- 09:00 — procesadas: 0, omitidas: 0, fallidas: 0 · 0 tokens · <1 min"
        " · detenida: LLM no disponible",
        "- 10:00 (manual) — procesadas: 6, omitidas: 1, fallidas: 0 · 39711 tokens · 4 min",
    ]


def test_the_queue_section_prefers_a_readable_label_over_a_raw_path_or_url(vault, queue):
    queue.add("https://x.test/a", origin="inbox")
    queue.add("/vault/raw/inbox/clip-1234.md", origin="inbox", label="Un gran post")

    assert build(vault, queue)["Cola de mañana"] == [
        "2 fuentes en cola.",
        "- https://x.test/a",
        "- Un gran post",
    ]


def test_review_also_lists_items_that_are_retrying_with_attempt_number_and_last_error(vault, queue):
    queue.add("https://bad.test/x", origin="inbox")
    queue.fail(queue.claim(1)[0].id, "ExtractError: nada legible")
    queue.add("/vault/raw/inbox/clip.md", origin="inbox", label="Un clip")
    queue.add("https://fresh.test/never-tried", origin="inbox")
    clip = queue.claim(1, exclude=[1])[0]
    queue.fail(clip.id, "ValueError: plan inválido")
    queue.fail(clip.id, "ValueError: plan inválido otra vez")

    assert build(vault, queue)["Por revisar"] == [
        "- Reintentando https://bad.test/x (intento 1 de 3): ExtractError: nada legible",
        "- Reintentando Un clip (intento 2 de 3): ValueError: plan inválido otra vez",
    ]


def test_a_queued_link_that_already_has_a_note_is_not_listed_as_pending(vault, queue):
    page = add_source(vault, "Ya está en la wiki")
    page.meta["url"] = "https://x.test/known?utm_source=mail"
    vault.write_page(page)
    queue.add("https://x.test/known", origin="inbox")  # run time would skip it with no model call
    queue.add("https://x.test/new", origin="inbox")

    index = build_daily_index(vault, queue, TODAY).read_text(encoding="utf-8")
    parsed = sections(index)

    assert parsed["Cola de mañana"] == ["1 fuente en cola.", "- https://x.test/new"]
    assert "- En cola: 1 fuentes" in (vault.root / "Home.md").read_text(encoding="utf-8")


def _record_runs(vault, *stops):
    """One scheduled run per hour from 03:05, each stopped by the given reason."""
    log = RunLog(vault.root / ".esbi" / "runs.jsonl")
    for hour, stopped_by in enumerate(stops, start=3):
        at = datetime(2026, 9, 29, hour, 5)
        log.record(RunRecord(at, at, 0, 0, 0, 0, stopped_by, "scheduled"))


def test_an_outage_in_the_last_run_is_the_first_thing_the_review_section_says(vault, queue):
    queue.add("https://x.test/a", origin="inbox")
    queue.add("https://x.test/b", origin="inbox")
    _record_runs(vault, "llm_unavailable")

    review = build(vault, queue)["Por revisar"]

    assert review == [
        "- El servidor del modelo no estaba disponible en la última ejecución (2026-09-29 03:05): "
        "2 fuentes esperan. Inicia Ollama o revisa el modelo y ejecuta `sb run`."
    ]


def test_the_outage_line_is_written_in_the_notes_language_and_counts_one_source(vault, queue):
    english = Vault(vault.root, language="en")
    queue.add("https://x.test/a", origin="inbox")
    _record_runs(vault, "llm_unavailable")

    assert build(english, queue)["To review"] == [
        "- The model server was unreachable in the last run (2026-09-29 03:05): 1 source is "
        "waiting. Start Ollama or check the model, then run `sb run`."
    ]


def test_the_outage_line_goes_away_once_a_later_run_reached_the_model(vault, queue):
    queue.add("https://x.test/a", origin="inbox")
    _record_runs(vault, "llm_unavailable", "max_sources")
    assert build(vault, queue)["Por revisar"] == ["_Nada pendiente._"]

    _record_runs(vault, "max_sources", "llm_unavailable")  # the outage is the latest again
    assert "servidor del modelo" in build(vault, queue)["Por revisar"][0]
