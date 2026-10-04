"""The Web Clipper template we ship must produce notes the worker reads as intended."""

import json
import re
from pathlib import Path

import pytest
import yaml

from esbi_cli.extract import extract_source

DOCS = Path(__file__).parent.parent / "src" / "esbi_cli" / "templates"
TEMPLATES = ["clipper-template.json", "clipper-youtube-template.json"]
PAGE = {
    "title": 'Una "gran" página: sobre agentes',
    "url": "https://example.test/articulo?utm_source=x",
    "author": "Ada Lovelace",
    "published": "2026-09-01",
    "content": "Texto del artículo sobre agentes de IA y su arnés de código. " * 8,
    "description": "Una descripción.",
    "transcript": "Texto del artículo sobre agentes de IA y su arnés de código. " * 8,
}


def render(template: dict) -> str:
    """What the Clipper writes: the properties as YAML frontmatter, then the note content."""

    def fill(value: str) -> str:
        return re.sub(r"\{\{(\w+)[^}]*\}\}", lambda m: PAGE.get(m.group(1), ""), value)

    meta = {p["name"]: fill(p["value"]) for p in template["properties"]}
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    return f"---\n{front}---\n\n{fill(template['noteContentFormat'])}\n"


@pytest.mark.parametrize("name", TEMPLATES)
def test_the_template_saves_into_the_inbox_with_the_properties_the_worker_reads(name):
    template = json.loads((DOCS / name).read_text(encoding="utf-8"))

    assert template["behavior"] == "create" and template["path"] == "inbox"
    names = {p["name"] for p in template["properties"]}
    assert {"title", "source", "kind"} <= names
    assert "{{title" in template["noteNameFormat"]  # the file name comes from the page title


@pytest.mark.parametrize("name", TEMPLATES)
def test_a_clip_made_with_the_template_is_read_back_with_its_title_url_and_text(tmp_path, name):
    template = json.loads((DOCS / name).read_text(encoding="utf-8"))
    clip = tmp_path / "Una gran página.md"
    clip.write_text(render(template), encoding="utf-8")

    doc = extract_source(str(clip))

    assert doc.title == PAGE["title"] and doc.url == PAGE["url"]
    assert "Texto del artículo" in doc.text and "source:" not in doc.text
