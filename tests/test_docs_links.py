"""Every relative link in the documentation points at a file and a heading that exist."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    *sorted((ROOT / "docs").rglob("*.md")),
]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def anchors(path: Path) -> set[str]:
    found, inside = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            inside = not inside
        elif not inside and (m := re.match(r"#{1,6}\s+(.*)", line)):
            found.add(slug(m[1]))
    return found


def links(path: Path):
    text, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            inside = not inside
        elif not inside:
            text.append(line)
    return LINK.findall("\n".join(text))


def test_every_relative_link_and_anchor_in_the_docs_resolves():
    broken = []
    for doc in (d for d in DOCS if d.exists()):
        for target in links(doc):
            if re.match(r"[a-z]+:", target):  # http, https, mailto
                continue
            file_part, _, anchor = target.partition("#")
            dest = (doc.parent / file_part).resolve() if file_part else doc
            if not dest.exists():
                broken.append(f"{doc.relative_to(ROOT)}: {target} (no such file)")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                broken.append(f"{doc.relative_to(ROOT)}: {target} (no such heading)")
    assert broken == []
