from pathlib import Path

import pytest

from esbi_cli.vault import Page, Vault, fold, parse_page, safe_title, slugify


def test_safe_title_strips_wikilink_and_path_characters():
    assert safe_title("A [[b]] / c: d?") == "A b c d"
    assert safe_title("../../etc/passwd") == "etc passwd"


def test_slugify_folds_accents():
    assert slugify("Arnés de Agentes: ¿qué?") == "arnes-de-agentes-que"


def test_page_roundtrip_with_frontmatter():
    page = Page(
        Path("x.md"), {"title": "Café", "sources": ["[[A]]"], "read": None}, "# Café\n\ntexto"
    )
    parsed = parse_page(Path("x.md"), page.render())
    assert parsed.meta == {"title": "Café", "sources": ["[[A]]"], "read": None}
    assert parsed.body == "# Café\n\ntexto"


def test_find_page_matches_title_and_alias_ignoring_case_and_accents(vault: Vault):
    vault.write_page(
        Page(
            vault.page_path("concepts", "Arnés de agente"),
            {"title": "Arnés de agente", "aliases": ["agent harness"]},
            "x",
        )
    )
    assert vault.find_page("arnes DE agente").title == "Arnés de agente"
    assert vault.find_page("Agent Harness").title == "Arnés de agente"
    assert vault.find_page("otra cosa") is None


def test_write_outside_vault_is_refused(vault: Vault):
    with pytest.raises(ValueError, match="outside the vault"):
        vault.write_page(Page(vault.root.parent / "evil.md", {}, "x"))


def test_fold():
    assert fold("  ÁÉÍ ñ ") == "aei n"
