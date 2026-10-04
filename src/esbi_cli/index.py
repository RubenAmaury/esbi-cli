"""A persistent index of the wiki's pages, in one SQLite file inside the vault.

Finding a page by name, a source by URL, or the pages related to a text used to mean reading and
parsing every page of the vault each time (a lookup took 240 ms at 1,000 pages and 1.2 s at 5,000,
and one ingest does about 30). The index keeps names, URLs, hashes and the full text, and only
re-reads the files whose size or modification time changed. It is disposable: delete the file and
the next lookup rebuilds it from the vault."""

import re
import sqlite3
import sys
from array import array
from math import sqrt
from operator import mul
from pathlib import Path

from esbi_cli.llm.adapter import LLMError
from esbi_cli.privacy import public_body
from esbi_cli.vault import PAGE_KINDS, Page, fold, parse_page

VERSION = "2"  # 2: the vectors table
CHUNK_CHARS = 3000  # a longer section is embedded by its first part; split it if that matters
QUERY_CHARS = 2000  # an ingest query is a whole source: the model reads its beginning
POOL = 50  # candidates taken from each side before fusing
RRF_K = 60  # reciprocal rank fusion constant (the usual one; 10 and 30 measured no differently)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE, kind TEXT, ord INTEGER, title TEXT, summary TEXT,
    url TEXT, content_hash TEXT, mtime_ns INTEGER, size INTEGER);
CREATE TABLE IF NOT EXISTS names (name TEXT, page_id INTEGER);
CREATE INDEX IF NOT EXISTS names_name ON names (name);
CREATE INDEX IF NOT EXISTS pages_url ON pages (url);
CREATE INDEX IF NOT EXISTS pages_hash ON pages (content_hash);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    title, aliases, body, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS vectors (page_id INTEGER, chunk INTEGER, vec BLOB);
CREATE INDEX IF NOT EXISTS vectors_page ON vectors (page_id);
"""


def chunks(title: str, body: str) -> list[str]:
    """The texts a page is embedded as: its introduction and each `## ` section, every one led by
    the page title (a section alone often does not say what it is about)."""
    head, *rest = re.split(r"^## ", body, flags=re.M)
    parts = [head.strip(), *("## " + r.strip() for r in rest)]
    return [f"{title}\n{p[:CHUNK_CHARS]}" for p in parts if p] or [title]


def _unit(vector: list[float]) -> array:
    norm = sqrt(sum(x * x for x in vector)) or 1.0
    return array("f", (x / norm for x in vector))


def rrf(*rankings: list[int]) -> list[int]:
    """Reciprocal rank fusion: an item scores 1/(k+rank) in every list it appears in."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            score[item] = score.get(item, 0.0) + 1 / (RRF_K + rank + 1)
    return sorted(score, key=lambda item: -score[item])


class Index:
    def __init__(self, root: Path, embedder=None, private=None):
        """`embedder` adds the dense side to `search` (None: keywords only, as always). `private()`
        returns (titles, source titles) of email-derived pages, asked only when the embedder
        sends text out."""
        self.embedder, self.private = embedder, private
        self.embed_down = False  # set once a call fails: the rest of this run is keywords only
        self.root = root
        self.db_path = root / ".esbi" / "index.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = self._open()

    def _open(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        current = None
        try:
            current = con.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        except sqlite3.DatabaseError:  # no tables yet, or not a database at all
            pass
        if current is None or current[0] != VERSION:  # a different layout: rebuild from the vault
            con.close()
            self.db_path.unlink(missing_ok=True)
            con = sqlite3.connect(self.db_path)
            con.executescript(_SCHEMA)
            con.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (VERSION,))
            con.commit()
        return con

    def _on_disk(self) -> dict[str, tuple[int, int, str, int]]:
        found = {}
        for order, kind in enumerate(PAGE_KINDS):
            folder = self.root / "wiki" / kind
            for path in folder.glob("*.md") if folder.is_dir() else ():
                stat = path.stat()
                found[str(path)] = (stat.st_mtime_ns, stat.st_size, kind, order)
        return found

    def sync(self) -> None:
        """Bring the index in line with the files: re-read only what is new or changed."""
        disk = self._on_disk()
        known = {
            path: (mtime, size)
            for path, mtime, size in self.con.execute("SELECT path, mtime_ns, size FROM pages")
        }
        for path in known.keys() - disk.keys():
            self._delete(path)
        for path, (mtime, size, kind, order) in disk.items():
            if known.get(path) != (mtime, size):
                page = parse_page(Path(path), Path(path).read_text(encoding="utf-8"))
                self._store(page, mtime, size, kind, order)
        self.con.commit()

    def upsert(self, page: Page) -> None:
        """Record a page the worker has just written, so the next lookup needs no re-read."""
        path = page.path.resolve()
        stat = path.stat()
        kind = path.parent.name
        if kind in PAGE_KINDS and path.parent.parent.name == "wiki":
            self._store(page, stat.st_mtime_ns, stat.st_size, kind, PAGE_KINDS.index(kind))
            self.con.commit()

    def _delete(self, path: str) -> None:
        row = self.con.execute("SELECT id FROM pages WHERE path = ?", (path,)).fetchone()
        if row:
            for table, column in (
                ("names", "page_id"),
                ("vectors", "page_id"),
                ("fts", "rowid"),
                ("pages", "id"),
            ):
                self.con.execute(f"DELETE FROM {table} WHERE {column} = ?", (row[0],))

    def _store(self, page: Page, mtime: int, size: int, kind: str, order: int) -> None:
        path = str(page.path.resolve())
        self._delete(path)
        meta = page.meta
        cur = self.con.execute(
            "INSERT INTO pages (path, kind, ord, title, summary, url, content_hash, mtime_ns, size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                path,
                kind,
                order,
                page.title,
                str(meta.get("summary", "")),
                str(meta["url"]) if meta.get("url") else None,
                str(meta["content_hash"]) if meta.get("content_hash") else None,
                mtime,
                size,
            ),
        )
        page_id = cur.lastrowid
        names = {fold(str(n)) for n in (page.path.stem, page.title, *page.aliases)}
        self.con.executemany("INSERT INTO names VALUES (?, ?)", [(n, page_id) for n in names])
        self.con.execute(
            "INSERT INTO fts (rowid, title, aliases, body) VALUES (?, ?, ?, ?)",
            (page_id, page.title, " ".join(page.aliases), page.body),
        )

    def find_path(self, title: str, kinds: tuple[str, ...]) -> Path | None:
        self.sync()
        marks = ",".join("?" * len(kinds))
        row = self.con.execute(
            "SELECT p.path FROM pages p JOIN names n ON n.page_id = p.id "
            f"WHERE n.name = ? AND p.kind IN ({marks}) ORDER BY p.ord, p.path LIMIT 1",
            (fold(title), *kinds),
        ).fetchone()
        return Path(row[0]) if row else None

    def find_source_path(self, key: str, value: str) -> Path | None:
        self.sync()
        column = {"url": "url", "content_hash": "content_hash"}.get(key)
        if column is None:  # any other frontmatter key: not indexed, the caller scans
            raise KeyError(key)
        row = self.con.execute(
            f"SELECT path FROM pages WHERE kind = 'sources' AND {column} = ? ORDER BY path LIMIT 1",
            (value,),
        ).fetchone()
        return Path(row[0]) if row else None

    def search(
        self,
        words: list[str],
        limit: int,
        exclude=frozenset(),
        query: str | None = None,
        private: bool = False,
    ) -> list[tuple[str, str, str]]:
        """(title, kind, summary) of the best matches, best first: keyword matches for any of
        `words`, fused with the pages whose meaning is closest to `query` when there is an
        embedder. `private`: the query is email text, which a remote embedder must not see."""
        self.sync()
        pool = limit + len(exclude)
        dense = self._dense(query, private)
        if dense is not None:
            pool = max(pool, POOL)
        ids = self._keyword_ids(words, pool)
        if dense is not None:
            ids = rrf(ids, dense)
        rows = []
        for page_id in ids:
            row = self.con.execute(
                "SELECT title, kind, summary FROM pages WHERE id = ?", (page_id,)
            ).fetchone()
            if row[0] not in exclude:
                rows.append(row)
        return rows[:limit]

    def _keyword_ids(self, words: list[str], pool: int) -> list[int]:
        if not words:
            return []
        query = " OR ".join(f'"{w}"' for w in words)
        rows = self.con.execute(
            "SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 5.0, 3.0, 1.0) LIMIT ?",
            (query, pool),
        ).fetchall()
        return [r[0] for r in rows]

    def _dense(self, query: str | None, private: bool) -> list[int] | None:
        """Page ids by meaning, best first; None when there is no dense side to use (no embedder,
        nothing to embed, or it failed: then search is keywords only, and says so once)."""
        emb = self.embedder
        if emb is None or not query or self.embed_down or (private and emb.sends_text_out):
            return None
        try:
            self._embed_pending(emb)
            vector = _unit(emb.embed([query[:QUERY_CHARS]], query=True)[0])
        except LLMError as exc:
            self.embed_down = True
            print(
                f"warning: embeddings unavailable ({exc}); searching by keyword only",
                file=sys.stderr,
            )
            return None
        best: dict[int, float] = {}
        # Known ceiling: plain Python over every chunk (about 30 microseconds each); numpy or
        # sqlite-vec when a vault passes some tens of thousands of chunks
        for page_id, blob in self.con.execute("SELECT page_id, vec FROM vectors WHERE chunk >= 0"):
            other = array("f")
            other.frombytes(blob)
            score = sum(map(mul, vector, other))
            if score > best.get(page_id, -2.0):
                best[page_id] = score
        return sorted(best, key=lambda i: -best[i])[:POOL]

    def _embed_pending(self, emb) -> None:
        """Embed the pages that have no vectors yet (new or changed: `_delete` drops theirs)."""
        stored = self.con.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()
        if stored is None or stored[0] != emb.identity:  # another model: its vectors are useless
            self.con.execute("DELETE FROM vectors")
            self.con.execute("INSERT OR REPLACE INTO meta VALUES ('embedder', ?)", (emb.identity,))
        rows = self.con.execute(
            "SELECT p.id, p.title, f.body FROM pages p JOIN fts f ON f.rowid = p.id "
            "WHERE p.id NOT IN (SELECT page_id FROM vectors)"
        ).fetchall()
        if not rows:
            self.con.commit()
            return
        hidden, shared = self.private() if emb.sends_text_out and self.private else ((), ())
        todo = []
        for page_id, title, body in rows:
            if title in hidden:  # email stays here: a marker says "left out on purpose"
                self.con.execute("INSERT INTO vectors VALUES (?, -1, x'')", (page_id,))
            else:
                todo.append((page_id, chunks(title, public_body(body, shared) if shared else body)))
        for i in range(0, len(todo), 8):  # whole pages per call, so a stop never leaves half a page
            group = todo[i : i + 8]
            texts = [c for _, cs in group for c in cs]
            vectors = iter(emb.embed(texts))
            for page_id, cs in group:
                for n in range(len(cs)):
                    self.con.execute(
                        "INSERT INTO vectors VALUES (?, ?, ?)",
                        (page_id, n, _unit(next(vectors)).tobytes()),
                    )
            self.con.commit()
        self.con.commit()

    def body_matches(self, names: list[str], sync: bool = True) -> set[str] | None:
        """Paths of the pages whose text contains any of `names` as whole words (case and accents
        ignored): a superset of what lint then checks exactly. None when a name cannot be
        searched (no letters or digits in it), so the caller falls back to looking at every page.
        A caller asking many times in a row syncs once itself and passes `sync=False`."""
        if sync:
            self.sync()
        phrases = []
        for name in names:
            if not re.search(r"\w", name):
                return None
            phrases.append('"' + name.replace('"', '""') + '"')
        try:
            rows = self.con.execute(
                "SELECT p.path FROM fts JOIN pages p ON p.id = fts.rowid WHERE fts MATCH ?",
                (f"body : ({' OR '.join(phrases)})",),
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        return {r[0] for r in rows}
