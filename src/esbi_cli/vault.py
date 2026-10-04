"""Reading and writing the Obsidian vault: pages, frontmatter, wikilink-safe titles."""

import hashlib
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from esbi_cli import lang

PAGE_KINDS = ("sources", "concepts", "entities", "syntheses")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_UNSAFE_TITLE = re.compile(r'[\[\]#|^:/\\?*"<>]')


def fold(text: str) -> str:
    """Lowercase and strip accents, for case/accent-insensitive title matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def safe_title(text: str, max_len: int = 100) -> str:
    """A title usable as an Obsidian filename and wikilink target. Control and invisible-format
    characters (escape sequences, direction overrides) are dropped: titles end up in file names,
    notes and terminal output."""
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    cleaned = _UNSAFE_TITLE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:max_len].strip(" .")


def free_path(folder: Path, filename: str) -> Path:
    """`folder/filename`, or `folder/name (2).ext`, `(3)`... if that is taken: never overwrite."""
    path = folder / filename
    n = 2
    while path.exists():
        path = folder / f"{Path(filename).stem} ({n}){Path(filename).suffix}"
        n += 1
    return path


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    if (
        not slug and text.strip()
    ):  # another script (Cyrillic, CJK...): a stable name, not "untitled"
        return "x-" + hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:10]
    return slug[:max_len].strip("-") or "untitled"


@dataclass
class Page:
    path: Path
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.path.stem

    @property
    def kind(self) -> str:
        return self.path.parent.name

    @property
    def aliases(self) -> list[str]:
        return list(self.meta.get("aliases") or [])

    def render(self) -> str:
        front = yaml.safe_dump(
            self.meta, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"


def parse_page(path: Path, text: str) -> Page:
    match = _FRONTMATTER.match(text)
    if not match:
        return Page(path=path, meta={}, body=text)
    meta = yaml.safe_load(match.group(1)) or {}
    return Page(path=path, meta=meta if isinstance(meta, dict) else {}, body=match.group(2).strip())


class Vault:
    def __init__(self, root: Path, embedder=None, language: str = lang.DEFAULT):
        self.root = root.resolve()
        self.language = language  # what the worker writes into the wiki: see lang.py
        self.embedder = embedder  # None: search by keyword only (see index.py)
        self._index = None  # opened on first use: see index.py

    @property
    def index(self):
        if self._index is None:
            from esbi_cli.index import Index  # imported here: index.py imports this module
            from esbi_cli.privacy import private_sources, private_titles

            self._index = Index(
                self.root,
                self.embedder,
                lambda: (private_titles(self), private_sources(self)),
            )
        return self._index

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    def validate(self) -> None:
        for needed in (self.root / "SCHEMA.md", self.wiki):
            if not needed.exists():
                raise FileNotFoundError(f"{needed} not found; is {self.root} a esbi-cli vault?")

    def schema_text(self) -> str:
        return (self.root / "SCHEMA.md").read_text(encoding="utf-8")

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"Refusing to write outside the vault: {path}")
        return resolved

    def page_path(self, kind: str, title: str) -> Path:
        name = safe_title(title)
        if not name:
            raise ValueError(f"Empty page title after sanitizing: {title!r}")
        return self._inside(self.wiki / kind / f"{name}.md")

    def iter_pages(self, kinds: tuple[str, ...] = PAGE_KINDS) -> Iterator[Page]:
        for kind in kinds:
            folder = self.wiki / kind
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.md")):
                yield parse_page(path, path.read_text(encoding="utf-8"))

    def read_page(self, path: Path) -> Page:
        return parse_page(path, path.read_text(encoding="utf-8"))

    def write_page(self, page: Page) -> None:
        target = self._inside(page.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.render(), encoding="utf-8")
        self.index.upsert(Page(target, page.meta, page.body))

    def find_page(self, title: str, kinds: tuple[str, ...] = PAGE_KINDS) -> Page | None:
        """Find a page by title or alias, ignoring case and accents."""
        path = self.index.find_path(title, kinds)
        return self.read_page(path) if path else None

    def resolve_page(self, ref: str, kinds: tuple[str, ...] = PAGE_KINDS) -> Page | None:
        """Like find_page, but tolerant of how LLMs echo titles back.

        Accepts `[[Title]]`, `Title (kind)`, `Title: summary` and `Title — summary`.
        """
        ref = ref.strip()
        variants = [ref, ref.removeprefix("[[").removesuffix("]]")]
        variants.append(re.sub(r"\s*\([^)]*\)\s*$", "", variants[-1]))
        for sep in (":", " — ", " - "):
            variants.append(variants[-1].split(sep)[0])
        for variant in dict.fromkeys(v.strip() for v in variants if v.strip()):
            if page := self.find_page(variant, kinds):
                return page
        return None

    def find_source(self, key: str, value: str) -> Page | None:
        """Find a source note whose frontmatter `key` equals `value` (e.g. url, content_hash)."""
        try:
            path = self.index.find_source_path(key, value)
            return self.read_page(path) if path else None
        except KeyError:  # a key the index does not keep: scan
            pass
        for page in self.iter_pages(("sources",)):
            if page.meta.get(key) == value:
                return page
        return None

    def append_log(
        self, entry: str, details: list[str] | None = None, day: date | None = None
    ) -> None:
        day = day or date.today()
        log = self._inside(self.root / "log.md")
        lines = [f"\n## [{day.isoformat()}] {entry}"] + [f"- {d}" for d in details or []]
        with log.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
