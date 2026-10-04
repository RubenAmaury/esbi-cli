from datetime import date

from conftest import add_source, write_daily

from esbi_cli.lint.checks import lint_vault
from esbi_cli.lint.report import write_lint_report
from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.vault import Page


def add_page(vault, kind, title, body="", **meta):
    fields = {"type": kind.rstrip("s"), "title": title, "summary": f"Resumen de {title}.", **meta}
    page = Page(vault.page_path(kind, title), fields, body or f"# {title}")
    vault.write_page(page)
    return page


def issues(vault, kind):
    return sorted((i.page, i.detail) for i in lint_vault(vault).issues if i.kind == kind)


def test_a_page_nothing_links_to_is_an_orphan(vault):
    add_source(vault, "Fuente A", body="# A\n\n## Conceptos\n- [[Concepto 1]]")
    add_page(vault, "concepts", "Concepto 1", "# Concepto 1\n\n## Desde [[Fuente A]]\nTexto")
    add_page(vault, "concepts", "Concepto suelto")

    assert [page for page, _ in issues(vault, "orphan")] == ["Concepto suelto"]


def test_links_to_missing_pages_are_broken_but_aliases_headings_and_special_pages_resolve(vault):
    add_page(vault, "concepts", "Real", aliases=["Alias real"])
    (vault.root / "Home.md").write_text("home")
    write_daily(vault, "2026-09-29", "nota del día")
    add_source(
        vault,
        "Fuente",
        body="[[Real]] [[Alias real]] [[Real#Sección]] [[Real|otro nombre]] [[Home]] "
        "[[2026-09-29]] [[Nada]] [[nada mas|x]] [[Nada]]",
    )

    assert issues(vault, "broken-link") == [("Fuente", "[[Nada]]"), ("Fuente", "[[nada mas]]")]


def test_pages_without_a_title_or_a_summary_are_flagged(vault):
    add_page(vault, "concepts", "Sin resumen", summary="")
    vault.write_page(Page(vault.page_path("concepts", "Sin título"), {"summary": "x"}, "texto"))
    add_page(vault, "concepts", "Completo")

    assert issues(vault, "missing-field") == [("Sin resumen", "summary"), ("Sin título", "title")]


def test_a_concept_named_in_another_page_without_a_link_is_an_unlinked_mention(vault):
    add_page(vault, "concepts", "Arnés de agente", aliases=["agent harness"])
    add_page(vault, "concepts", "IA")  # too short to be worth flagging
    add_source(vault, "Sin enlace", body="# S\n\nEl arnés de agente coordina todo y la IA ayuda.")
    add_source(vault, "Con enlace", body="# C\n\nEl [[Arnés de agente]] coordina todo.")
    add_source(vault, "Por alias", body="# P\n\nEl Agent Harness es clave.")
    add_source(
        vault, "Palabra parcial", body="# X\n\nUn arnés de agentes distintos, no el concepto."
    )

    assert issues(vault, "unlinked-mention") == [
        ("Por alias", "Arnés de agente"),
        ("Sin enlace", "Arnés de agente"),
    ]


def test_near_duplicate_concepts_are_flagged_once_per_pair(vault):
    add_page(vault, "concepts", "Agente")
    add_page(vault, "concepts", "Agentes")  # plural variant
    add_page(vault, "concepts", "Arnés", aliases=["harness"])
    add_page(vault, "entities", "Harness")  # its title is another page's alias
    add_page(vault, "concepts", "Atención")
    add_page(vault, "concepts", "Atencion")  # accent variant
    add_page(vault, "concepts", "Harness Interface")
    add_page(vault, "concepts", "Harness Mechanisms")  # related, but different concepts
    add_page(vault, "concepts", "Cocina italiana")

    assert issues(vault, "near-duplicate") == [
        ("Agente", "Agentes"),
        ("Arnés", "Harness"),
        ("Atencion", "Atención"),
    ]


TODAY = date(2026, 9, 29)


def test_the_lint_report_exists_only_while_there_are_problems(vault, queue):
    add_page(vault, "concepts", "Suelto")
    add_source(vault, "Fuente", body="# F\n\nVer [[No existe]]")

    path = write_lint_report(vault, lint_vault(vault), TODAY)

    assert path == vault.wiki / "review" / "Lint.md"
    text = path.read_text(encoding="utf-8")
    assert "## Páginas huérfanas" in text and "- [[Suelto]]" in text
    assert "## Enlaces rotos" in text and "- [[Fuente]] → `[[No existe]]`" in text
    daily = build_daily_index(vault, queue, TODAY).read_text(encoding="utf-8")
    assert "- [[Lint]]" in daily.split("## Por revisar")[1].split("## ")[0]

    vault.page_path("concepts", "Suelto").unlink()
    vault.page_path("sources", "Fuente").unlink()
    assert write_lint_report(vault, lint_vault(vault), TODAY) is None
    assert not path.exists()


def test_a_long_list_of_problems_is_cut_off_with_a_count(vault):
    pairs = [a + b for a in "abcdefghij" for b in "klmnopqrst"]  # 100 distinct pairs
    for pair in pairs[:55]:  # unrelated names, so only the orphan section is long
        add_page(vault, "concepts", pair * 3)

    text = write_lint_report(vault, lint_vault(vault), TODAY).read_text(encoding="utf-8")

    assert text.count("\n- [[") == 50 and "… y 5 más" in text


def test_single_word_names_are_flagged_only_on_an_exact_case_sensitive_match(vault):
    """Real wiki: 100 hits, many for common words the model turned into concepts."""
    add_page(vault, "concepts", "Enfoque")
    add_page(vault, "entities", "Palantir")
    add_page(vault, "concepts", "Modelo Transformer")
    add_source(vault, "Común", body="# C\n\nEl enfoque es simple y usa un modelo transformer.")
    add_source(vault, "Propio", body="# P\n\nTrabajó en Palantir. Enfoque: mixto.")

    assert issues(vault, "unlinked-mention") == [
        ("Común", "Modelo Transformer"),  # multi-word: still matched ignoring case
        ("Propio", "Enfoque"),
        ("Propio", "Palantir"),
    ]


def glossary_source(vault, title, *terms):
    lines = "\n".join(f"- **{t}**: una definición cualquiera del término." for t in terms)
    add_source(vault, title, body=f"# {title}\n\n## Términos clave\n{lines}\n\n## Conceptos\n- x")


def test_a_term_defined_by_two_sources_with_no_page_of_its_own_is_suggested_as_a_concept(vault):
    glossary_source(vault, "Fuente A", "Working Memory", "Solo en A")
    glossary_source(vault, "Fuente B", "working memory", "Con página")
    glossary_source(vault, "Fuente C", "Con página")
    add_page(vault, "concepts", "Con página")

    found = issues(vault, "missing-concept")

    assert found == [("Working Memory", "Fuente A, Fuente B")]  # "Solo en A" has one source only


def test_the_report_names_the_sources_that_use_a_term_that_deserves_a_page(vault):
    glossary_source(vault, "Fuente A", "Working Memory")
    glossary_source(vault, "Fuente B", "Working Memory")

    write_lint_report(vault, lint_vault(vault), date(2026, 10, 1))

    text = (vault.wiki / "review" / "Lint.md").read_text(encoding="utf-8")
    assert "## Conceptos sin página" in text
    assert "«Working Memory» aparece en [[Fuente A]], [[Fuente B]]" in text


def test_an_embedded_image_that_exists_in_the_vault_is_not_a_broken_link(vault):
    (vault.root / "attachments" / "fuente-a").mkdir(parents=True)
    (vault.root / "attachments" / "fuente-a" / "fig-1.png").write_bytes(b"\x89PNG")
    add_source(
        vault,
        "Fuente A",
        body="# A\n\n![[attachments/fuente-a/fig-1.png|600]]\n![[attachments/fuente-a/fig-9.png|600]]",
    )

    found = issues(vault, "broken-link")

    assert found == [("Fuente A", "[[attachments/fuente-a/fig-9.png]]")]  # only the missing one


def test_lint_only_inspects_the_pages_that_could_mention_a_name_not_every_pair(vault, monkeypatch):
    """At 1,000 pages the all-pairs scan took 44 s; the full-text index narrows each name to the
    pages that contain it."""
    from esbi_cli.lint import checks

    for n in range(12):
        add_page(vault, "concepts", f"Concepto único{n}x")
        add_source(vault, f"Fuente {n}", body=f"# F\n\nTexto sin relación alguna {n}.")
    add_source(
        vault,
        "Menciona",
        body="# M\n\nHabla del Concepto únicoNNx 7 y de otras cosas.".replace(
            "únicoNNx 7", "único7x"
        ),
    )
    calls = []
    real = checks._mentions
    monkeypatch.setattr(checks, "_mentions", lambda *a: calls.append(1) or real(*a))

    found = issues(vault, "unlinked-mention")

    assert found == [("Menciona", "Concepto único7x")]
    assert len(calls) <= 3  # not 12 targets x 25 pages


def test_near_duplicates_are_still_found_without_comparing_every_pair(vault):
    for title in ("Agente de código", "Agentes de código", "Cocina italiana", "Astronomía"):
        add_page(vault, "concepts", title)
    add_page(vault, "concepts", "Otro nombre", aliases=["Astronomía"])  # shared alias

    pairs = {frozenset(pair) for pair in issues(vault, "near-duplicate")}

    assert pairs == {
        frozenset({"Agente de código", "Agentes de código"}),
        frozenset({"Astronomía", "Otro nombre"}),
    }
