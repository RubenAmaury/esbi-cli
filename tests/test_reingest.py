"""Rebuilding the wiki from the saved raw sources."""

import subprocess
from datetime import date

from conftest import FakeLLM, make_plan

from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.llm.adapter import LLMTimeout
from esbi_cli.reingest import reingest_all

DAY = date(2026, 9, 29)
LATER = date(2026, 9, 30)


def concept(title, word="Descripción"):
    return {"title": title, "aliases": [], "description": f"{word} de {title}."}


def seed(vault, cfg):
    """Two ingested sources: A has its own concept and a shared one, B only the shared one."""
    docs = {
        "Fuente A": ExtractedDoc(
            "Fuente A", "Texto de la fuente A sobre agentes. " * 30, "article", "https://x.test/a"
        ),
        "Fuente B": ExtractedDoc(
            "Fuente B", "Texto de la fuente B sobre agentes. " * 30, "article", "https://x.test/b"
        ),
    }
    plans = {
        "Fuente A": make_plan(
            title="Fuente A", concepts=[concept("Solo de A"), concept("Compartido")], entities=[]
        ),
        "Fuente B": make_plan(title="Fuente B", concepts=[concept("Compartido")], entities=[]),
    }
    for title, doc in docs.items():
        ingest(
            "x",
            vault=vault,
            llm=FakeLLM(plans[title]),
            cfg=cfg,
            extractor=lambda _, d=doc: d,
            today=DAY,
        )
    return docs


def legacy(vault, title, **meta):
    """Make a note look like it came from the old pipeline (no `format`), with extra metadata."""
    page = vault.read_page(vault.page_path("sources", title))
    page.meta.pop("format", None)
    page.meta.update(meta)
    vault.write_page(page)


def tags(vault):
    return subprocess.run(
        ["git", "tag"], cwd=vault.root, capture_output=True, text=True
    ).stdout.split()


def new_plans(*titles):
    return [
        make_plan(
            title=t,
            summary=f"Nuevo resumen ejecutivo de {t}, mucho más útil que el anterior.",
            concepts=[concept("Nuevo de A", "Novedad"), concept("Compartido", "Novedad")]
            if t == "Fuente A"
            else [concept("Compartido", "Novedad")],
            entities=[],
        )
        for t in titles
    ]


def test_notes_are_rebuilt_keeping_their_title_read_state_and_date_and_the_raw_files(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A", status="read", read="2026-09-29", tags=["mio"])
    legacy(vault, "Fuente B")
    raw_before = sorted(p.name for p in (vault.root / "raw").iterdir())

    result = reingest_all(
        vault, FakeLLM(*new_plans("Fuente A", "Fuente B")), None, cfg, today=LATER
    )

    assert result.done == ["Fuente A", "Fuente B"] and result.skipped == []
    a = vault.read_page(vault.page_path("sources", "Fuente A"))
    assert "Nuevo resumen ejecutivo de Fuente A" in a.body
    assert (a.meta["status"], a.meta["read"], a.meta["captured"]) == (
        "read",
        "2026-09-29",
        "2026-09-29",
    )
    assert a.meta["format"] == 2 and a.meta["processed"] == "2026-09-30"
    assert sorted(p.name for p in (vault.root / "raw").iterdir()) == raw_before  # no new snapshots


def test_what_the_old_note_added_to_concept_pages_is_replaced_not_piled_up(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")

    reingest_all(vault, FakeLLM(*new_plans("Fuente A", "Fuente B")), None, cfg, today=LATER)

    assert not vault.page_path("concepts", "Solo de A").exists()  # only A made it, A dropped it
    assert vault.page_path("concepts", "Nuevo de A").exists()
    shared = vault.read_page(vault.page_path("concepts", "Compartido"))
    assert (
        shared.body.count("## Desde [[Fuente A]]") == 1
        and shared.body.count("## Desde [[Fuente B]]") == 1
    )
    assert sorted(shared.meta["sources"]) == ["[[Fuente A]]", "[[Fuente B]]"]
    assert "Descripción de Compartido" not in shared.body and "Novedad de Compartido" in shared.body


def test_the_vault_is_tagged_first_so_a_bad_rebuild_is_one_command_to_undo(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")

    reingest_all(vault, FakeLLM(*new_plans("Fuente A", "Fuente B")), None, cfg, today=LATER)

    [tag] = [t for t in tags(vault) if t.startswith("pre-reingest-")]
    before = subprocess.run(
        ["git", "show", f"{tag}:wiki/sources/Fuente A.md"],
        cwd=vault.root,
        capture_output=True,
        text=True,
    )
    assert "Nuevo resumen" not in before.stdout  # the tag holds the old version


def test_notes_already_in_the_new_format_are_left_alone_unless_all_is_forced(vault, cfg):
    seed(vault, cfg)  # both freshly ingested: format 2
    llm = FakeLLM(*new_plans("Fuente A", "Fuente B"))

    untouched = reingest_all(vault, llm, None, cfg, today=LATER)
    assert untouched.done == [] and llm.calls == []

    forced = reingest_all(vault, llm, None, cfg, today=LATER, all_sources=True)
    assert forced.done == ["Fuente A", "Fuente B"]


def test_a_note_whose_raw_snapshot_is_gone_is_skipped_with_the_reason_and_the_rest_go_on(
    vault, cfg
):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")
    raw_a = vault.root / vault.read_page(vault.page_path("sources", "Fuente A")).meta["raw"]
    raw_a.unlink()

    result = reingest_all(vault, FakeLLM(*new_plans("Fuente B")), None, cfg, today=LATER)

    assert result.done == ["Fuente B"]
    assert result.skipped and result.skipped[0][0] == "Fuente A" and "raw" in result.skipped[0][1]
    assert vault.page_path("sources", "Fuente A").exists()  # the old note is kept, not deleted


def test_a_note_whose_model_call_times_out_fails_alone_and_the_rest_are_rebuilt(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")

    result = reingest_all(
        vault, FakeLLM(LLMTimeout("timed out"), *new_plans("Fuente B")), None, cfg, today=LATER
    )

    assert result.done == ["Fuente B"] and not result.stopped
    assert (
        result.failed and result.failed[0][0] == "Fuente A" and "timed out" in result.failed[0][1]
    )
    assert "Nuevo resumen" not in vault.read_page(vault.page_path("sources", "Fuente A")).body


def test_what_the_model_got_wrong_is_reported_per_note_not_lost(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")
    plans = new_plans("Fuente A", "Fuente B")
    plans[0]["one_liner"] = "https://x.test/a"  # unusable: repaired, and worth a warning

    result = reingest_all(vault, FakeLLM(*plans), None, cfg, today=LATER)

    assert [title for title, _ in result.warnings] == ["Fuente A"]


def test_only_the_named_notes_are_rebuilt_even_if_they_are_already_in_the_new_format(vault, cfg):
    seed(vault, cfg)  # both already format 2

    result = reingest_all(
        vault, FakeLLM(*new_plans("Fuente B")), None, cfg, today=LATER, only=["fuente b"]
    )

    assert result.done == ["Fuente B"]
    assert "Nuevo resumen" not in vault.read_page(vault.page_path("sources", "Fuente A")).body


def test_progress_tells_how_much_time_is_left_once_one_note_is_done(vault, cfg):
    seed(vault, cfg)
    legacy(vault, "Fuente A")
    legacy(vault, "Fuente B")
    lines = []

    reingest_all(
        vault,
        FakeLLM(*new_plans("Fuente A", "Fuente B")),
        None,
        cfg,
        today=LATER,
        on_progress=lines.append,
    )

    headers = [line for line in lines if line.startswith("[")]
    assert "left" not in headers[0] and "left" in headers[1]  # nothing to estimate from at first
