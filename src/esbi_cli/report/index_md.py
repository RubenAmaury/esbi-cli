"""Rebuild index.md deterministically from page frontmatter (no LLM needed)."""

from esbi_cli import lang
from esbi_cli.vault import Vault, fold

SECTIONS = ("sources", "concepts", "entities", "syntheses")  # page folders, and their label keys


def rebuild_index(vault: Vault) -> None:
    by_kind: dict[str, list[tuple[str, str]]] = {kind: [] for kind in SECTIONS}
    for page in vault.iter_pages():
        by_kind[page.kind].append((page.title, str(page.meta.get("summary") or "")))
    total = sum(len(v) for v in by_kind.values())
    L = vault.language
    lines = [f"# {lang.t(L, 'index_title')}", "", lang.t(L, "index_blurb", total=total), ""]
    for kind in SECTIONS:
        lines += [f"## {lang.t(L, kind)} ({len(by_kind[kind])})", ""]
        for title, summary in sorted(by_kind[kind], key=lambda t: fold(t[0])):
            lines.append(f"- [[{title}]]" + (f" — {summary}" if summary else ""))
        lines.append("")
    (vault.root / "index.md").write_text("\n".join(lines), encoding="utf-8")
