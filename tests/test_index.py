"""The persistent page index: lookups no longer read every page of the vault."""

import sqlite3

from conftest import add_source

from esbi_cli import index as index_module
from esbi_cli.ingest.retrieve import find_candidates
from esbi_cli.vault import Page, Vault


def add_concept(vault, title, body="# C", **meta):
    fields = {"type": "concept", "title": title, "summary": f"Resumen de {title}.", **meta}
    vault.write_page(Page(vault.page_path("concepts", title), fields, body))


def count_reads(monkeypatch):
    reads = []
    real = index_module.parse_page
    monkeypatch.setattr(
        index_module, "parse_page", lambda path, text: reads.append(path) or real(path, text)
    )
    return reads


def test_a_page_is_found_by_title_alias_or_file_name_ignoring_case_and_accents(vault):
    add_concept(vault, "Arnés de agente", aliases=["Agent Harness"])
    add_source(vault, "Una fuente")

    assert vault.find_page("arnes de AGENTE").title == "Arnés de agente"
    assert vault.find_page("agent harness").title == "Arnés de agente"
    assert vault.find_page("una fuente", ("concepts",)) is None  # the kind filter holds
    assert vault.find_page("una fuente", ("sources",)).title == "Una fuente"
    assert vault.find_page("no existe") is None


def test_pages_that_did_not_change_are_not_read_again(vault, monkeypatch):
    for n in range(20):
        add_concept(vault, f"Concepto {n}")
    reads = count_reads(monkeypatch)

    fresh = Vault(vault.root)  # a new process: the index file already exists on disk
    fresh.find_page("Concepto 3")
    fresh.find_page("Concepto 17")
    fresh.find_page("Concepto que no existe")

    assert reads == []  # all 20 were indexed when they were written; nothing is re-parsed


def test_an_edit_made_outside_the_worker_and_a_deleted_page_are_noticed(vault):
    add_concept(vault, "Viejo")
    assert vault.find_page("Viejo") is not None

    path = vault.page_path("concepts", "Viejo")
    path.write_text(
        "---\ntitle: Nuevo nombre\n---\n\ntexto", encoding="utf-8"
    )  # edited in Obsidian
    assert vault.find_page("Nuevo nombre").path == path
    assert vault.find_page("Viejo").path == path  # the file name still resolves

    path.unlink()
    assert vault.find_page("Nuevo nombre") is None and vault.find_page("Viejo") is None


def test_the_index_is_disposable_deleting_the_file_rebuilds_it(vault):
    add_concept(vault, "Uno")
    add_source(vault, "Dos")
    vault.find_page("Uno")
    db = vault.root / ".esbi" / "index.sqlite3"
    assert db.exists()
    db.unlink()

    fresh = Vault(vault.root)

    assert fresh.find_page("Uno").title == "Uno" and fresh.find_page("Dos").title == "Dos"


def test_a_source_is_found_by_url_or_content_hash_without_scanning(vault, monkeypatch):
    page = add_source(vault, "Con url")
    page.meta.update({"url": "https://x.test/a", "content_hash": "abc123"})
    vault.write_page(page)
    reads = count_reads(monkeypatch)

    fresh = Vault(vault.root)

    assert fresh.find_source("url", "https://x.test/a").title == "Con url"
    assert fresh.find_source("content_hash", "abc123").title == "Con url"
    assert fresh.find_source("url", "https://x.test/otra") is None and reads == []


def test_related_pages_come_from_the_stored_full_text_index_with_exclusions(vault):
    add_concept(
        vault, "Arnés de agente", body="El arnés orquesta herramientas y memoria del agente."
    )
    add_concept(vault, "Cocina", body="Recetas de pasta y salsas.")
    add_concept(vault, "Privado", body="El arnés del contrato secreto.")

    found = find_candidates(Vault(vault.root), "arnés herramientas memoria agente contrato")
    assert [c.title for c in found][:2] == ["Arnés de agente", "Privado"] and "Cocina" not in [
        c.title for c in found
    ]

    hidden = find_candidates(Vault(vault.root), "arnés herramientas memoria", exclude={"Privado"})
    assert [c.title for c in hidden] == ["Arnés de agente"]
    assert hidden[0].one_liner == "Resumen de Arnés de agente." and hidden[0].kind == "concepts"


def test_a_changed_page_is_searched_by_its_new_text(vault):
    add_concept(vault, "Tema", body="Algo sobre jardinería.")
    assert find_candidates(vault, "jardinería") != []
    add_concept(vault, "Tema", body="Ahora trata de astronomía.")

    assert find_candidates(vault, "jardinería") == []
    assert [c.title for c in find_candidates(vault, "astronomía")] == ["Tema"]


def test_the_index_file_keeps_a_version_so_a_different_layout_is_rebuilt(vault):
    add_concept(vault, "Uno")
    vault.find_page("Uno")
    db = vault.root / ".esbi" / "index.sqlite3"
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value = '0' WHERE key = 'version'")
    con.commit()
    con.close()

    assert Vault(vault.root).find_page("Uno").title == "Uno"
