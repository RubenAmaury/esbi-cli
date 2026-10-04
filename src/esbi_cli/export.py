"""A read-only static copy of the wiki (plain HTML files), for people who browse without Obsidian."""

import html
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from markdown_it import MarkdownIt

from esbi_cli import lang
from esbi_cli.vault import Page, Vault, fold, slugify

MARKER = ".esbi-site"
_EMBED = re.compile(r"!\[\[([^\]|]+?)(?:\|(\d+))?\]\]")
_LINK = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+?))?\]\]")
_STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --bg: #ffffff; --muted: #6a737d; --line: #d8dee4; --link: #0b5cad; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --bg: #0d1117; --muted: #8b949e; --line: #30363d; --link: #58a6ff; } }
body { font: 16px/1.6 system-ui, sans-serif; color: var(--fg); background: var(--bg); max-width: 46rem; margin: 0 auto; padding: 1rem; }
a { color: var(--link); } nav { border-bottom: 1px solid var(--line); margin-bottom: 1rem; padding-bottom: .5rem; }
img { max-width: 100%; height: auto; } pre { overflow-x: auto; } blockquote { border-left: 3px solid var(--line); margin-left: 0; padding-left: 1rem; color: var(--muted); }
li.src small { color: var(--muted); } table { border-collapse: collapse; } td, th { border: 1px solid var(--line); padding: .25rem .5rem; }
"""
_MERMAID = (
    '<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/'
    'mermaid.esm.min.mjs"; mermaid.initialize({startOnLoad: true});</script>'
)


def _page_html(title: str, body: str, root: str, language: str) -> str:
    script = _MERMAID if 'class="mermaid"' in body else ""
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        f'<nav><a href="{root}index.html">esbi-cli</a></nav>{body}{script}</body></html>'
    )


def export_site(vault: Vault, out: Path) -> int:
    """Write the wiki as HTML into `out` (replacing an earlier export). Returns the page count."""
    out = out.expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        old_marker = out / ".second-brain-site"  # legacy: the name before esbi-cli
        if not (out / MARKER).exists() and not old_marker.exists():
            raise ValueError(
                f"{out} is not an export of this wiki and has other files: not touching it"
            )
        for child in out.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("written by `sb export`; safe to replace\n", encoding="utf-8")

    pages = list(vault.iter_pages())
    taken: dict[str, set[str]] = {}
    where: dict[Page, str] = {}  # page -> "kind/slug.html"
    names: dict[str, str] = {}
    for page in pages:
        slug, used = slugify(page.title), taken.setdefault(page.kind, set())
        n = 2
        while slug in used:
            slug, n = f"{slugify(page.title)}-{n}", n + 1
        used.add(slug)
        where[id(page)] = f"{page.kind}/{slug}.html"
        for name in (page.path.stem, page.title, *page.aliases):
            names.setdefault(fold(str(name)), where[id(page)])

    # html False: a note is written from untrusted pages and mail, and the export is a website, so
    # raw HTML in a note is shown as text. Links and images are written as Markdown below.
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    for page in pages:

        def embed(m: re.Match) -> str:
            return f"![]({quote('../' + m[1].strip(), safe='/')})"

        def link(m: re.Match) -> str:
            target = names.get(fold(m[1].strip()))
            label = (m[2] or m[1].strip()).replace("[", "\\[").replace("]", "\\]")
            return f"[{label}](../{quote(target, safe='/')})" if target else label

        text = _LINK.sub(link, _EMBED.sub(embed, page.body))
        body = md.render(text)
        body = body.replace('<pre><code class="language-mermaid">', '<pre class="mermaid"><code>')
        body = re.sub(
            r'<pre class="mermaid"><code>(.*?)</code></pre>',
            r'<pre class="mermaid">\1</pre>',
            body,
            flags=re.S,
        )
        body = body.replace("<li>[x] ", "<li>☑ ").replace("<li>[ ] ", "<li>☐ ")
        target = out / where[id(page)]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_page_html(page.title, body, "../", vault.language), encoding="utf-8")

    if (vault.root / "attachments").is_dir():
        shutil.copytree(vault.root / "attachments", out / "attachments", dirs_exist_ok=True)
    (out / "index.html").write_text(_index(pages, where, vault.language), encoding="utf-8")
    return len(pages)


def _index(pages: list[Page], where: dict, language: str) -> str:
    def items(selected: list[Page]) -> str:
        rows = []
        for p in selected:
            summary = html.escape(str(p.meta.get("summary") or ""))
            rows.append(
                f'<li class="src"><a href="{where[id(p)]}">{html.escape(p.title)}</a>'
                + (f"<br><small>{summary}</small>" if summary else "")
                + "</li>"
            )
        return f"<ul>{''.join(rows)}</ul>"

    sections = []
    sources = sorted(
        (p for p in pages if p.kind == "sources"),
        key=lambda p: (str(p.meta.get("processed", "")), p.title),
        reverse=True,
    )
    for heading, selected in (
        (lang.t(language, "sources"), sources),
        (
            lang.t(language, "concepts"),
            sorted((p for p in pages if p.kind == "concepts"), key=lambda p: fold(p.title)),
        ),
        (
            lang.t(language, "entities"),
            sorted((p for p in pages if p.kind == "entities"), key=lambda p: fold(p.title)),
        ),
        (
            lang.t(language, "syntheses"),
            sorted((p for p in pages if p.kind == "syntheses"), key=lambda p: fold(p.title)),
        ),
    ):
        if selected:
            sections.append(f"<h2>{heading} ({len(selected)})</h2>{items(selected)}")
    return _page_html("esbi-cli", "<h1>esbi-cli</h1>" + "".join(sections), "", language)
