"""Connections: how a new source relates to what the wiki already knows."""

from dataclasses import replace
from datetime import date

from conftest import FakeLLM, add_source, make_plan

from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest

TODAY = date(2026, 9, 30)
DOC = ExtractedDoc(
    "Verificación de agentes",
    "La verificación automática de resultados hace fiables a los agentes de código. " * 30,
    "article",
    "https://x.test/verificacion",
)


def connections(*items):
    return {"connections": [{"page": p, "relation": r, "why": w} for p, r, w in items]}


def run(vault, cfg, llm, doc=DOC):
    return ingest("x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: doc, today=TODAY)


def existing_wiki(vault):
    add_source(
        vault,
        "Arnés de agentes",
        summary="Un arnés de código rodea al modelo y orquesta herramientas y memoria.",
        body="# Arnés de agentes\n\nEl arnés gestiona contexto y verificación de agentes de código.",
    )


def test_a_new_source_is_connected_to_existing_pages_with_the_reason(vault, cfg):
    existing_wiki(vault)
    cfg = replace(cfg, find_connections=True)
    llm = FakeLLM(
        make_plan(title="Verificación de agentes"),
        connections(
            ("Arnés de agentes", "amplía", "Profundiza en la verificación, una pieza del arnés.")
        ),
    )

    result = run(vault, cfg, llm)

    body = vault.read_page(result.applied.source_path).body
    assert "## Conexiones con tu wiki" in body
    assert (
        "- [[Arnés de agentes]]: **amplía**. Profundiza en la verificación, una pieza del arnés."
        in body
    )
    connect_prompt = llm.calls[1]["user"]  # the second call
    assert (
        "Un arnés de código rodea al modelo" in connect_prompt
    )  # existing pages come with their summary
    assert (
        "Un arnés de código rodea al modelo" not in llm.calls[0]["user"]
    )  # the digest stays uncontaminated


def test_invented_pages_and_links_to_itself_are_dropped_and_nothing_is_asked_when_the_wiki_is_empty(
    vault, cfg
):
    cfg = replace(cfg, find_connections=True)
    empty = FakeLLM(make_plan(title="Verificación de agentes"))
    run(vault, cfg, empty)
    assert len(empty.calls) == 1  # no existing pages: no connection call at all

    existing_wiki(vault)
    other = ExtractedDoc(
        "Otra",
        "La verificación automática de agentes de código. " * 30,
        "article",
        "https://x.test/otra",
    )
    llm = FakeLLM(
        make_plan(title="Otra fuente sobre verificación"),
        connections(
            ("Página inventada", "amplía", "Esta página no existe en la wiki de nadie."),
            (
                "Otra fuente sobre verificación",
                "amplía",
                "Se relaciona consigo misma, lo cual no tiene sentido.",
            ),
            ("Arnés de agentes", "complementa", "Comparte el enfoque de verificar los resultados."),
        ),
    )
    result = run(vault, cfg, llm, other)

    body = vault.read_page(result.applied.source_path).body
    assert body.count("**") >= 2 and "Página inventada" not in body
    assert "[[Arnés de agentes]]: **complementa**" in body
    assert "Página inventada" in result.applied.dropped


def test_connections_can_be_turned_off_and_a_failed_connection_step_never_fails_the_source(
    vault, cfg
):
    existing_wiki(vault)
    off = FakeLLM(make_plan(title="Verificación de agentes"))
    run(vault, replace(cfg, find_connections=False), off)
    assert len(off.calls) == 1

    broken = FakeLLM(make_plan(title="Verificación B"), "no es json", "tampoco")
    other = ExtractedDoc(
        "B", "Texto distinto sobre verificación y agentes. " * 30, "article", "https://x.test/b"
    )
    result = run(vault, replace(cfg, find_connections=True), broken, other)

    assert result.status == "ingested" and any("connections" in w.lower() for w in result.warnings)


def test_a_rebuilt_note_is_not_offered_the_pages_it_created_itself_as_connections(vault, cfg):
    existing_wiki(vault)  # someone else's page: still a candidate
    run(vault, cfg, FakeLLM(make_plan(title="Verificación de agentes")))  # makes the concept page
    cfg = replace(cfg, find_connections=True)
    llm = FakeLLM(
        make_plan(title="Verificación de agentes"),
        connections(("Arnés de agentes", "amplía", "Profundiza en la verificación del arnés.")),
    )

    ingest(
        "x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: DOC, today=TODAY,
        force=True, keep_title="Verificación de agentes",
    )  # fmt: skip

    offered = llm.calls[1]["user"].split("<existing_pages>")[1]
    assert "Arnés de agentes" in offered and "Arnés de agente [" not in offered


def test_a_page_the_model_connects_several_times_is_listed_once(vault, cfg):
    """Seen on the real vault: eight identical lines for the same page."""
    existing_wiki(vault)
    cfg = replace(cfg, find_connections=True)
    same = ("Arnés de agentes", "aplica", "Se relaciona con el arnés de agentes de código.")
    llm = FakeLLM(make_plan(title="Verificación de agentes"), connections(same, same, same))

    result = run(vault, cfg, llm)

    body = vault.read_page(result.applied.source_path).body
    assert body.count("- [[Arnés de agentes]]: **aplica**") == 1


def test_a_page_this_note_just_created_or_extended_is_a_concept_not_a_connection(vault, cfg):
    from esbi_cli.vault import Page

    page = Page(
        vault.page_path("concepts", "Arnés"),
        {"type": "concept", "title": "Arnés", "sources": [], "summary": "El arnés de un agente."},
        "# Arnés\n\nEl arnés de código de un agente.",
    )
    vault.write_page(page)
    cfg = replace(cfg, find_connections=True)
    concept = {"title": "Arnés", "aliases": [], "description": "Aquí también aparece el arnés."}
    plan = make_plan(title="Verificación de agentes", concepts=[concept])
    llm = FakeLLM(plan, connections(("Arnés", "aplica", "Es el mismo arnés de agentes de código.")))

    result = run(vault, cfg, llm)

    body = vault.read_page(result.applied.source_path).body
    assert "## Conceptos" in body and "[[Arnés]]" in body
    assert "## Conexiones con tu wiki" not in body  # shown under Conceptos already
