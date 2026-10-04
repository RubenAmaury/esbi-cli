"""`sb export`: a read-only static copy of the wiki, for people who browse without Obsidian."""

from conftest import add_source
from typer.testing import CliRunner

from esbi_cli.cli import app
from esbi_cli.export import export_site
from esbi_cli.vault import Page

BODY = """# Fuente uno

## Resumen ejecutivo
Habla del [[Arnés de agente]], de [[Algo que no existe]] y de [[Arnés de agente|el arnés]].

## Diagrama
```mermaid
graph LR
  n1["A"] -- "usa" --> n2["B"]
```

## Figuras
![[attachments/fuente-uno/fig-1.png|600]]
*Figura 1 (p. 3)*

- [x] leído
- [ ] pendiente
"""


def build(vault):
    add_source(vault, "Fuente uno", body=BODY, summary="Resumen de la fuente uno.")
    vault.write_page(
        Page(
            vault.page_path("concepts", "Arnés de agente"),
            {
                "type": "concept",
                "title": "Arnés de agente",
                "aliases": ["agent harness"],
                "summary": "Capa de código.",
            },
            "# Arnés de agente\n\n## Desde [[Fuente uno]]\nLa capa de código del agente.",
        )
    )
    (vault.root / "attachments" / "fuente-uno").mkdir(parents=True)
    (vault.root / "attachments" / "fuente-uno" / "fig-1.png").write_bytes(b"\x89PNG fake")


def test_every_page_becomes_a_html_file_and_wikilinks_become_relative_links(vault, tmp_path):
    build(vault)
    out = tmp_path / "site"

    count = export_site(vault, out)

    assert count == 2
    source = (out / "sources" / "fuente-uno.html").read_text(encoding="utf-8")
    assert '<a href="../concepts/arnes-de-agente.html">Arnés de agente</a>' in source
    assert (
        '<a href="../concepts/arnes-de-agente.html">el arnés</a>' in source
    )  # the alias text is kept
    assert "[[" not in source and "Algo que no existe" in source  # an unresolved link is plain text
    concept = (out / "concepts" / "arnes-de-agente.html").read_text(encoding="utf-8")
    assert '<a href="../sources/fuente-uno.html">Fuente uno</a>' in concept


def test_images_diagrams_and_ticks_are_kept_in_a_form_a_browser_shows(vault, tmp_path):
    build(vault)
    out = tmp_path / "site"

    export_site(vault, out)

    source = (out / "sources" / "fuente-uno.html").read_text(encoding="utf-8")
    assert '<img src="../attachments/fuente-uno/fig-1.png"' in source
    assert (out / "attachments" / "fuente-uno" / "fig-1.png").read_bytes() == b"\x89PNG fake"
    assert (
        '<pre class="mermaid">' in source and "mermaid" in source.split("</pre>")[-1]
    )  # the script
    assert "☑ leído" in source and "☐ pendiente" in source


def test_the_front_page_lists_what_there_is_and_pages_link_back_to_it(vault, tmp_path):
    build(vault)
    out = tmp_path / "site"

    export_site(vault, out)

    index = (out / "index.html").read_text(encoding="utf-8")
    assert (
        '<a href="sources/fuente-uno.html">Fuente uno</a>' in index
        and "Resumen de la fuente uno." in index
    )
    assert '<a href="concepts/arnes-de-agente.html">Arnés de agente</a>' in index
    assert 'href="../index.html"' in (out / "sources" / "fuente-uno.html").read_text(
        encoding="utf-8"
    )


def test_an_export_can_be_repeated_but_a_folder_that_is_not_an_export_is_never_wiped(
    vault, tmp_path
):
    build(vault)
    out = tmp_path / "site"
    export_site(vault, out)
    export_site(vault, out)  # a second time replaces the first

    precious = tmp_path / "mis-cosas"
    precious.mkdir()
    (precious / "importante.txt").write_text("no tocar")
    try:
        export_site(vault, precious)
    except ValueError as exc:
        assert "not an export" in str(exc)
    else:
        raise AssertionError("must refuse to write into a folder that has other files")
    assert (precious / "importante.txt").read_text() == "no tocar"


def test_the_command_writes_the_site_and_says_where(vault, config_file, tmp_path):
    build(vault)
    out = tmp_path / "web"

    result = CliRunner().invoke(app, ["export", "--out", str(out), "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert "2 pages" in result.stdout and str(out / "index.html") in result.stdout
    assert (out / "index.html").exists()
