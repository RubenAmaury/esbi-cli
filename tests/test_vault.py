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


@pytest.mark.parametrize(
    "title",
    ["日本語" * 40, "🚀" * 100, "é" * 150, "L" * 300],
    ids=["japanese", "emoji", "accents", "ascii"],
)
def test_a_title_always_fits_a_file_name_of_255_bytes_with_room_for_extension_and_counter(title):
    # ext4 (Linux, WSL) limits a name to 255 BYTES, not characters: 100 emoji or 90 Japanese
    # characters used to fail with "File name too long" and the source was parked as failed
    name = safe_title(title)

    assert name and len((name + " (99).md").encode("utf-8")) <= 255
    assert title.startswith(name)  # cut, never altered or split inside a character


def test_a_short_title_is_not_cut():
    assert safe_title("Arnés de agente 日本語") == "Arnés de agente 日本語"
