"""Concept and entity pages get one consolidated summary on top of their per-source sections."""

import subprocess
from datetime import date

import pytest
from conftest import FakeLLM, add_source, make_plan
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli.ask.answer import answer_question, page_context
from esbi_cli.cli import app
from esbi_cli.ingest.consolidate import consolidate_due, consolidate_pages, is_due
from esbi_cli.llm.adapter import LLMError
from esbi_cli.privacy import public_body
from esbi_cli.reingest import _forget
from esbi_cli.vault import Page, Vault

TODAY = date(2026, 10, 4)
SOURCES = {
    "Fuente A": "Un arnés de código organiza el contexto del agente y sus herramientas.",
    "Fuente B": "El arnés verifica los resultados de cada paso antes de continuar.",
    "Fuente C": "Anthropic describe el arnés como la capa que rodea al modelo.",
}
GOOD = (
    "El arnés de código organiza el contexto y las herramientas del agente, y verifica los "
    "resultados de cada paso antes de continuar. Anthropic lo describe como la capa que rodea al modelo."
)
ENGLISH = (
    "The code harness organises the context and the tools of the agent and checks the results "
    "of every step before the next one."
)
INVENTED = (
    "El arnés de código fue creado en 2019 por OpenAI y organiza el contexto y las herramientas "
    "del agente, según un estudio de la universidad."
)


def seed_page(
    vault, title="Arnés de agente", sources=None, *, kind="concepts", heading="Desde", **meta
):
    sources = SOURCES if sources is None else sources
    for name in sources:
        if not vault.find_page(name, ("sources",)):
            add_source(vault, name)
    body = f"# {title}\n\n" + "\n\n".join(
        f"## {heading} [[{name}]]\n{text}" for name, text in sources.items()
    )
    page = Page(
        vault.page_path(kind, title),
        {
            "type": "concept" if kind == "concepts" else "entity",
            "title": title,
            "aliases": [],
            "sources": [f"[[{name}]]" for name in sources],
            "updated": "2026-10-01",
            "summary": f"Resumen corto de {title}.",
            **meta,
        },
        body,
    )
    vault.write_page(page)
    return page


def make_email_source(vault, title):
    page = vault.read_page(vault.page_path("sources", title))
    page.meta["kind"] = "email"
    vault.write_page(page)


def summary(text):
    return {"summary": text}


def cloud(*payloads):
    llm = FakeLLM(*payloads)
    llm.sends_text_out = True
    return llm


def read(vault, title="Arnés de agente"):
    return vault.find_page(title, ("concepts", "entities"))


def run(vault, llm, *pages, **kw):
    return consolidate_pages(vault, list(pages), llm, today=TODAY, **kw)


def test_the_summary_goes_on_top_and_the_per_source_sections_stay_as_evidence(vault):
    page = seed_page(vault)
    llm = FakeLLM(summary(GOOD))

    result = run(vault, llm, page)

    after = read(vault)
    assert result.done == ["Arnés de agente"]
    assert after.body.startswith(
        f"# Arnés de agente\n\n## Resumen\n{GOOD}\n\n## Desde [[Fuente A]]"
    )
    assert all(f"## Desde [[{name}]]\n{text}" in after.body for name, text in SOURCES.items())
    assert after.meta["summary_sources"] == 3 and after.meta["updated"] == TODAY.isoformat()
    prompt = llm.calls[0]["user"]
    assert all(text in prompt for text in SOURCES.values())
    assert "Spanish" in llm.calls[0]["system"]


def test_the_heading_comes_from_the_language_catalogue(vault):
    english = Vault(vault.root, language="en")
    page = seed_page(english, heading="From")

    run(english, FakeLLM(summary(ENGLISH)), page)

    assert "\n## Summary\n" in read(english).body


def test_a_vault_that_switched_language_keeps_one_summary_and_every_section(vault):
    page = seed_page(vault, heading="From")  # sections written in English, notes now in Spanish
    run(vault, FakeLLM(summary(GOOD)), page)
    english = Vault(vault.root, language="en")

    run(english, FakeLLM(summary(ENGLISH)), read(english))

    body = read(english).body
    assert body.count("## Summary") == 1 and "## Resumen" not in body
    assert body.count("## From [[") == 3


def test_a_summary_that_adds_names_numbers_or_quotes_is_retried_once_then_goes_to_review(vault):
    page = seed_page(vault)
    llm = FakeLLM(summary(INVENTED), summary(INVENTED))
    before = vault.page_path("concepts", "Arnés de agente").read_text(encoding="utf-8")

    result = run(vault, llm, page)

    assert result.done == [] and len(llm.calls) == 2
    assert "invalid" in llm.calls[1]["user"] and "2019" in llm.calls[1]["user"]
    assert vault.page_path("concepts", "Arnés de agente").read_text(encoding="utf-8") == before
    [review] = result.reviews
    assert review.parent == vault.wiki / "review" and INVENTED in review.read_text(encoding="utf-8")


def test_a_second_try_that_passes_is_written(vault):
    page = seed_page(vault)
    llm = FakeLLM(summary(INVENTED), summary(GOOD))

    result = run(vault, llm, page)

    assert result.done and not result.reviews and f"## Resumen\n{GOOD}" in read(vault).body


@pytest.mark.parametrize(
    "bad",
    [
        'El arnés dice "nunca falla jamás" y organiza el contexto y las herramientas del agente con cuidado.',
        "El arnés organiza el contexto y las herramientas del agente; véase [[arnés]] para el detalle completo.",
        "El arnés organiza el contexto y las herramientas del agente <b>siempre</b> con mucho cuidado y orden.",
        "El arnés organiza el contexto y las herramientas del agente, ver http://a.test/x para el detalle completo.",
        "El arnés organiza el contexto y las herramientas del agente ![x](a.png) con mucho cuidado y orden.",
        "El arnés organiza el contexto y las herramientas del agente, [ver](obsidian://open) con mucho orden.",
        "Muy corto.",
        "x" * 1000,
    ],
)
def test_quotes_links_and_bad_lengths_are_rejected(vault, bad):
    page = seed_page(vault)

    result = run(vault, FakeLLM(summary(bad), summary(bad)), page)

    assert result.done == [] and len(result.reviews) == 1


def test_an_answer_in_the_wrong_language_is_retried(vault):
    page = seed_page(vault)
    english = (
        "The harness of code is used for the context and the tools of the agent, and it checks "
        "the results of each step before the next one in that case."
    )
    llm = FakeLLM(summary(english), summary(GOOD))

    result = run(vault, llm, page)

    assert result.done and len(llm.calls) == 2


def test_a_model_that_is_down_stops_the_batch_and_changes_nothing(vault):
    first, second = seed_page(vault), seed_page(vault, "Otro concepto")

    result = run(vault, FakeLLM(LLMError("down")), first, second)

    assert result.stopped and result.done == [] and "summary_sources" not in read(vault).meta


@pytest.mark.parametrize(
    ("sources", "last", "due"),
    [(2, None, False), (3, None, True), (3, 3, False), (4, 3, False), (5, 3, True), (2, 5, False)],
)
def test_a_page_is_due_at_three_sources_and_again_two_sources_later(vault, sources, last, due):
    names = {f"Fuente {n}": f"Texto {n}." for n in range(sources)}
    meta = {} if last is None else {"summary_sources": last}

    assert is_due(seed_page(vault, sources=names, **meta)) is due


def test_the_automatic_pass_is_bounded_and_skips_pages_that_are_not_due(vault):
    pages = [seed_page(vault, f"Concepto {n}") for n in range(3)]
    small = seed_page(vault, "Concepto pequeño", {"Fuente A": "Solo una fuente dice esto."})
    llm = FakeLLM(summary(GOOD), summary(GOOD))

    result = consolidate_due(vault, [p.title for p in (*pages, small)], llm, limit=2, today=TODAY)

    assert len(result.done) == 2 and len(llm.calls) == 2
    assert "summary_sources" not in read(vault, "Concepto pequeño").meta


def test_every_page_is_committed_on_its_own(vault):
    pages = [seed_page(vault, "Uno"), seed_page(vault, "Dos")]
    subprocess.run(["git", "add", "-A"], cwd=vault.root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=vault.root, check=True)

    run(vault, FakeLLM(summary(GOOD), summary(GOOD)), *pages)

    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True
    ).stdout.split("\n")
    assert log[:2] == ["consolidate: Dos", "consolidate: Uno"]


# --- privacy -----------------------------------------------------------------------------------


def email_page(vault):
    page = seed_page(
        vault, sources={**SOURCES, "Asunto privado": "El contrato Acme vence en marzo."}
    )
    make_email_source(vault, "Asunto privado")
    return page


def test_a_page_with_email_is_consolidated_only_by_the_private_model(vault):
    page = email_page(vault)
    writer, private = cloud(summary(GOOD)), FakeLLM(summary(GOOD))

    result = run(vault, writer, page, private=private)

    assert result.done and writer.calls == [] and "contrato Acme" in private.calls[0]["user"]


def test_a_page_with_email_and_no_private_model_is_left_alone_when_the_writer_sends_text_out(
    vault,
):
    page = email_page(vault)
    writer = cloud(summary(GOOD))

    result = run(vault, writer, page)

    assert result.done == [] and writer.calls == [] and result.skipped[0][0] == "Arnés de agente"
    assert "summary_sources" not in read(vault).meta


def test_a_private_model_that_sends_text_out_is_not_used_for_email(vault):
    page = email_page(vault)
    private = cloud(summary(GOOD))

    result = run(vault, FakeLLM(), page, private=private)

    assert result.done == [] and private.calls == []


def test_a_local_writer_may_consolidate_a_page_with_email(vault):
    page = email_page(vault)

    assert run(vault, FakeLLM(summary(GOOD)), page).done


def test_a_page_without_email_uses_the_synthesis_model_else_the_summarize_one(vault):
    page = seed_page(vault)
    reader, synth = FakeLLM(), FakeLLM(summary(GOOD))

    run(vault, reader, page, synth=synth)

    assert reader.calls == [] and len(synth.calls) == 1


def test_a_cloud_model_asked_a_question_never_sees_the_summary_of_a_page_with_email(vault):
    email_page(vault)
    run(vault, FakeLLM(summary(GOOD)), read(vault))
    public = seed_page(
        vault,
        "Memoria",
        {"Fuente A": "La memoria guarda el contexto.", "Fuente B": "La memoria se resume."},
    )
    memory = (
        "La memoria guarda el contexto del agente y se resume cuando crece demasiado para caber."
    )
    run(vault, FakeLLM(summary(memory)), public)
    answer = {
        "title": "Qué es el arnés",
        "one_liner": "Explicación breve del arnés.",
        "answer": "El arnés organiza el contexto ([[Arnés de agente]]) y la memoria ([[Memoria]]).",
        "cited_pages": ["Arnés de agente", "Memoria"],
    }
    llm = cloud(answer)

    answer_question(vault, llm, "¿Qué es el arnés de agente y la memoria?")

    prompt = llm.calls[0]["user"]
    assert GOOD not in prompt and "Acme" not in prompt and "## Resumen\nLa memoria guarda" in prompt
    local = FakeLLM(answer)
    answer_question(vault, local, "¿Qué es el arnés de agente?")
    assert GOOD in local.calls[0]["user"]


def test_the_public_part_of_a_page_drops_the_summary_when_an_email_section_is_dropped():
    body = f"# T\n\n## Resumen\n{GOOD}\n\n## Desde [[Fuente A]]\nPública.\n\n## Desde [[Mail]]\nPrivada."

    assert public_body(body, {"Mail"}) == "# T\n\n## Desde [[Fuente A]]\nPública."
    assert public_body(body, {"Otro"}) == body.strip()  # no email in the page: the summary stays


def test_forgetting_a_source_drops_the_summary_that_was_built_with_it(vault):
    page = seed_page(vault)
    run(vault, FakeLLM(summary(GOOD)), page)

    _forget(vault, vault.read_page(vault.page_path("sources", "Fuente B")))

    after = read(vault)
    assert "## Resumen" not in after.body and "summary_sources" not in after.meta
    assert "## Desde [[Fuente A]]" in after.body and "[[Fuente B]]" not in after.body


# --- readers -----------------------------------------------------------------------------------


def test_ask_puts_the_summary_first_and_still_fits_whole_sections_of_evidence(vault):
    body = (
        "# T\n\n## Resumen\n"
        + "s" * 40
        + "\n\n## From [[A]]\n"
        + "a" * 40
        + "\n\n## Desde [[B]]\n"
        + "b" * 40
        + "\n\n## Desde [[C]]\n"
        + "c" * 400
    )

    context = page_context(body, 180)

    assert (
        context.index("## Resumen")
        < context.index("## From [[A]]")
        < context.index("## Desde [[B]]")
    )
    assert "## Desde [[C]]" not in context  # too big for what is left: left out whole


# --- near-duplicates ---------------------------------------------------------------------------


def test_likely_duplicates_are_reported_in_review_never_merged(vault):
    page = seed_page(vault, "Inteligencia artificial")
    seed_page(vault, "IA", {"Fuente A": "La IA aparece aquí."})
    seed_page(vault, "Cocina italiana", {"Fuente A": "Pasta."})

    result = run(vault, FakeLLM(summary(GOOD)), page)

    [note] = result.suggestions
    text = note.read_text(encoding="utf-8")
    assert note.parent == vault.wiki / "review" and "[[IA]]" in text and "Cocina" not in text
    assert read(vault, "IA") is not None and "## Resumen" not in read(vault, "IA").body


def test_a_page_with_no_likely_duplicate_gets_no_review_note(vault):
    page = seed_page(vault)

    assert run(vault, FakeLLM(summary(GOOD)), page).suggestions == []


def test_a_dry_run_asks_no_model_and_writes_nothing(vault):
    page = seed_page(vault)
    llm = FakeLLM()

    result = run(vault, llm, page, dry_run=True)

    assert result.done == ["Arnés de agente"] and llm.calls == []
    assert "summary_sources" not in read(vault).meta


# --- the command -------------------------------------------------------------------------------


def clip(vault, name, text):
    (vault.root / "inbox" / name).write_text(
        f"---\nsource: https://x.test/{name}\n---\n{text * 8}", encoding="utf-8"
    )


def config_with(config_file, extra=""):
    """The test config with connections off (they would use up the fake model's answers)."""
    text = config_file.read_text(encoding="utf-8")
    text = text.replace("[run]\n", f"[run]\nfind_connections = false\n{extra}\n")
    config_file.write_text(text, encoding="utf-8")


def test_run_consolidates_a_concept_that_reached_three_sources(vault, config_file, monkeypatch):
    config_with(config_file)
    for n in "ABC":
        clip(vault, f"{n}.md", f"Texto de la fuente {n} sobre agentes y arneses de código. ")
    evidence = make_plan()["concepts"][0]["description"]
    good = f"{evidence.rstrip('.')}, según las tres fuentes que lo describen."
    llm = FakeLLM(*(make_plan(title=f"Fuente {n}") for n in "ABC"), summary(good))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    page = read(vault)
    assert page.meta["summary_sources"] == 3 and f"## Resumen\n{good}" in page.body
    assert "consolidated" in result.stdout


def test_the_nightly_run_asks_for_no_summary_when_none_is_due(vault, config_file, monkeypatch):
    config_with(config_file)
    clip(vault, "A.md", "Texto de la fuente A sobre agentes y arneses de código. ")
    llm = FakeLLM(make_plan(title="Fuente A"))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)

    assert CliRunner().invoke(app, ["run", "--config", str(config_file)]).exit_code == 0
    assert len(llm.calls) == 1


def test_max_consolidations_per_run_caps_the_automatic_pass(vault, config_file, monkeypatch):
    config_with(config_file, "max_consolidations_per_run = 0")
    for n in "ABC":
        clip(vault, f"{n}.md", f"Texto de la fuente {n} sobre agentes y arneses de código. ")
    llm = FakeLLM(*(make_plan(title=f"Fuente {n}") for n in "ABC"))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 0 and len(llm.calls) == 3


def test_consolidate_command_without_flags_takes_the_due_pages(vault, config_file, monkeypatch):
    seed_page(vault)
    seed_page(vault, "Ya resumido", summary_sources=3)
    seed_page(vault, "Entidad", kind="entities")
    llm = FakeLLM(summary(GOOD), summary(GOOD))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)

    result = CliRunner().invoke(app, ["consolidate", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert len(llm.calls) == 2 and "## Resumen" not in read(vault, "Ya resumido").body
    assert "consolidated: 2" in result.stdout


def test_consolidate_all_and_only(vault, config_file, monkeypatch):
    seed_page(vault, "Uno", summary_sources=3)
    seed_page(vault, "Dos", summary_sources=3)
    seed_page(vault, "Suelto", {"Fuente A": "Una sola fuente."})
    llm = FakeLLM(summary(GOOD), summary(GOOD), summary(GOOD))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)
    runner, args = CliRunner(), ["--config", str(config_file)]

    only = runner.invoke(app, ["consolidate", "--only", "uno", *args])
    everything = runner.invoke(app, ["consolidate", "--all", *args])

    assert only.exit_code == 0 and "consolidated: 1" in only.stdout
    assert "consolidated: 2" in everything.stdout  # Suelto has one source: nothing to consolidate
    assert len(llm.calls) == 3


def test_consolidate_dry_run_lists_pages_and_calls_no_model(vault, config_file, monkeypatch):
    seed_page(vault)
    llm = FakeLLM()
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: llm)

    result = CliRunner().invoke(app, ["consolidate", "--dry-run", "--config", str(config_file)])

    assert result.exit_code == 0 and "Arnés de agente" in result.stdout and llm.calls == []
    assert "summary_sources" not in read(vault).meta


def test_consolidate_exits_with_an_error_when_the_model_is_down(vault, config_file, monkeypatch):
    seed_page(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(LLMError("down")))

    result = CliRunner().invoke(app, ["consolidate", "--config", str(config_file)])

    assert result.exit_code == 1 and "unreachable" in result.output


def test_consolidate_documents_its_flags_in_help():
    out = CliRunner().invoke(app, ["consolidate", "--help"]).output

    assert "--all" in out and "--only" in out and "--dry-run" in out
