"""The rich source note: sections, and the guards that keep invented material out of it."""

from datetime import date

from conftest import FakeLLM, make_plan

from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest

TODAY = date(2026, 9, 30)

TEXT = (
    "Los agentes de IA usan un arnés de código para planificar y ejecutar herramientas. "
    "El arnés gestiona el contexto, la memoria y la verificación de resultados. "
    "«La verificación cierra el bucle entre el modelo y el mundo», según los autores. "
) * 4 + "Anthropic publica ejemplos de arneses de agentes."


def rich_plan(**overrides):
    plan = make_plan(
        summary="Un arnés de código rodea al modelo y le da memoria y verificación. Importa porque decide la fiabilidad.",
        abstract="El problema: los modelos solos fallan.\n\nEl enfoque: un arnés de código.\n\nLos hallazgos: la verificación es clave.",
        insights=[
            {
                "idea": "La verificación cierra el bucle.",
                "why": "Sin ella los errores se acumulan.",
            },
            {
                "idea": "El arnés importa más que el modelo.",
                "why": "Determina qué puede hacer el agente.",
            },
        ],
        terms=[
            {"term": "arnés de código", "definition": "La capa de código que rodea al modelo."},
            {"term": "Término inventado", "definition": "No aparece en la fuente por ningún lado."},
        ],
        quotes=[
            "La verificación cierra el bucle entre el modelo y el mundo",
            "Una frase que el autor jamás escribió en este texto.",
        ],
        relations=[
            {"a": "Arnés", "relation": "gestiona", "b": "Contexto"},
            {"a": "Arnés", "relation": "hace", "b": 'Verificación "final"'},
            {"a": "Verificación", "relation": "cierra", "b": "Bucle"},
        ],
        open_questions=["¿Cómo se mide la fiabilidad de un arnés?"],
    )
    plan.update(overrides)
    return plan


def note(vault, cfg, llm_payload, doc=None, **kw):
    doc = doc or ExtractedDoc("Arnés de agentes", TEXT, "article", "https://x.test/a")
    result = ingest(
        "x",
        vault=vault,
        llm=FakeLLM(llm_payload),
        cfg=cfg,
        extractor=lambda _: doc,
        today=TODAY,
        **kw,
    )
    return result, vault.read_page(result.applied.source_path).body


def section(body, heading):
    """The lines under `## heading`, up to the next `## `."""
    lines, out, on = body.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            on = line[3:].strip() == heading
        elif on:
            out.append(line)
    return "\n".join(out).strip()


def test_a_rich_plan_becomes_a_note_someone_who_has_not_read_the_source_can_use(vault, cfg):
    _, body = note(vault, cfg, rich_plan())

    assert "decide la fiabilidad" in section(body, "Resumen ejecutivo")
    detail = section(body, "Resumen detallado")
    assert detail.count("\n\n") == 2 and "El problema:" in detail and "Los hallazgos:" in detail
    ideas = section(body, "Ideas clave")
    assert "- **La verificación cierra el bucle.** Sin ella los errores se acumulan." in ideas
    assert "¿Cómo se mide la fiabilidad de un arnés?" in section(body, "Preguntas abiertas")


def test_quotes_must_really_be_in_the_source_and_terms_too(vault, cfg):
    result, body = note(vault, cfg, rich_plan())

    quotes = section(body, "Frases clave")
    assert '> "La verificación cierra el bucle entre el modelo y el mundo"' in quotes
    assert "jamás escribió" not in body  # an invented quote never reaches the note
    glossary = section(body, "Términos clave")
    assert "**arnés de código**: La capa de código que rodea al modelo." in glossary
    assert "Término inventado" not in body
    assert "Término inventado" in result.applied.unsupported_terms


def test_a_glossary_term_that_is_a_concept_page_is_linked(vault, cfg):
    plan = rich_plan(
        concepts=[
            {
                "title": "Arnés de código",
                "aliases": [],
                "description": "La capa que rodea al modelo.",
            }
        ]
    )
    _, body = note(vault, cfg, plan)
    assert "**[[Arnés de código]]**: La capa de código que rodea al modelo." in section(
        body, "Términos clave"
    )


def test_relations_are_drawn_as_a_valid_mermaid_concept_map_with_clean_labels(vault, cfg):
    _, body = note(vault, cfg, rich_plan())

    diagram = section(body, "Diagrama")
    assert diagram.startswith("```mermaid\ngraph LR") and diagram.endswith("```")
    assert 'n1["Arnés"] -- "gestiona" --> n2["Contexto"]' in diagram
    assert "Verificación 'final'" in diagram  # a double quote would break the diagram: replaced
    assert diagram.count("-->") == 3 and '""' not in diagram


def test_fewer_than_two_relations_means_no_diagram(vault, cfg):
    plan = rich_plan(relations=[{"a": "Arnés", "relation": "gestiona", "b": "Contexto"}])
    _, body = note(vault, cfg, plan)
    assert "## Diagrama" not in body


def test_a_plain_plan_still_gives_a_readable_note_with_the_old_sections(vault, cfg):
    _, body = note(vault, cfg, make_plan())

    assert "## Resumen ejecutivo" in body and "## Puntos clave" in body
    for empty in ("Frases clave", "Términos clave", "Diagrama", "Figuras", "Preguntas abiertas"):
        assert f"## {empty}" not in body  # no empty sections


def test_a_glossary_definition_left_in_english_is_dropped_with_its_term(vault, cfg):
    plan = rich_plan(
        terms=[
            {"term": "arnés de código", "definition": "La capa de código que rodea al modelo."},
            {"term": "arnés", "definition": "A software layer that wraps the model with tools."},
        ]
    )

    result, body = note(vault, cfg, plan)

    glossary = section(body, "Términos clave")
    assert "**arnés de código**" in glossary and "software layer" not in body
    assert "arnés" in result.applied.unsupported_terms  # reported like the other dropped terms


def test_a_quote_that_is_only_a_short_heading_is_not_a_key_phrase(vault, cfg):
    text = TEXT + "\n\n_Qué medio conecta el modelo con su entorno_\n"
    doc = ExtractedDoc("Arnés de agentes", text, "article", "https://x.test/a")
    plan = rich_plan(
        quotes=["_Qué medio conecta el modelo con su entorno_", rich_plan()["quotes"][0]]
    )

    _, body = note(vault, cfg, plan, doc=doc)

    quotes = section(body, "Frases clave")
    assert "Qué medio conecta" not in quotes and "cierra el bucle" in quotes


def test_a_detailed_summary_cut_off_mid_sentence_ends_at_its_last_full_sentence(vault, cfg):
    cut = "El problema: los modelos solos fallan. El enfoque: un arnés de código.\n\nEl modelo también utiliza una técnica llamada"

    _, body = note(vault, cfg, rich_plan(abstract=cut))

    detail = section(body, "Resumen detallado")
    assert detail.endswith("un arnés de código.") and "llamada" not in detail


VIDEO = ExtractedDoc(
    "Un vídeo sobre agentes",
    "## Transcript\n\n"
    "**0:00** · What would you do if I were not real? This is the opening line of the video.\n\n"
    "**2:20** · The agent harness is the code around the model, and it decides what the agent can do.\n\n"
    "**1:02:03** · Near the end an hour in, the speaker closes the argument about verification.",
    "video",
    "https://www.youtube.com/watch?v=abc123",
)


def test_quotes_and_terms_of_a_video_link_to_the_second_where_they_are_said(vault, cfg):
    plan = rich_plan(
        quotes=[
            "The agent harness is the code around the model, and it decides",
            "the speaker closes the argument about verification",
        ],
        terms=[{"term": "verification", "definition": "Comprobar el resultado del agente."}],
    )

    _, body = note(vault, cfg, plan, doc=VIDEO)

    link = "https://www.youtube.com/watch?v=abc123&t="
    quotes = section(body, "Frases clave")
    assert f"([2:20]({link}140s))" in quotes
    assert f"([1:02:03]({link}3723s))" in quotes
    assert f"**verification** ([1:02:03]({link}3723s)): Comprobar" in section(
        body, "Términos clave"
    )


def test_a_quote_from_something_that_is_not_a_video_has_no_timestamp(vault, cfg):
    _, body = note(vault, cfg, rich_plan())

    assert "](http" not in section(body, "Frases clave")
