from esbi_cli.bench.cases import load_cases
from esbi_cli.vault import Page


def write_raw(vault, name, title, text, url=None, kind="article"):
    meta = {"title": title, "url": url, "kind": kind, "captured": "2026-09-29"}
    vault.write_page(Page(vault.root / "raw" / f"{name}.md", meta, text))


def add_concept(vault, title):
    meta = {"type": "concept", "title": title, "summary": f"Resumen de {title}."}
    vault.write_page(Page(vault.page_path("concepts", title), meta, f"# {title}\n\nTexto."))


def test_cases_are_spread_evenly_over_the_vault_and_skip_sources_that_are_too_short(vault):
    for n in range(1, 6):
        write_raw(vault, f"2026-09-29-fuente-{n}", f"Fuente {n}", f"Texto de la fuente {n}. " * 60)
    write_raw(vault, "2026-09-29-corta", "Corta", "muy poco texto")
    for title in ("Alfa", "Beta", "Gamma", "Delta"):
        add_concept(vault, title)

    ingest_cases, ask_cases = load_cases(vault, n=3)

    assert [c.doc.title for c in ingest_cases] == ["Fuente 1", "Fuente 3", "Fuente 5"]
    assert (
        ingest_cases[0].doc.kind == "article"
        and "Texto de la fuente 1." in ingest_cases[0].doc.text
    )
    assert [c.question for c in ask_cases] == ["¿Qué es Alfa?", "¿Qué es Delta?", "¿Qué es Gamma?"]
    assert [c.expected for c in ask_cases] == [
        "Alfa",
        "Delta",
        "Gamma",
    ]  # first, middle, last (sorted)


def test_fewer_sources_than_requested_gives_all_of_them(vault):
    write_raw(vault, "2026-09-29-solo", "Solo", "Texto suficiente para contar como fuente. " * 30)

    ingest_cases, ask_cases = load_cases(vault, n=5)

    assert [c.doc.title for c in ingest_cases] == ["Solo"] and ask_cases == []
