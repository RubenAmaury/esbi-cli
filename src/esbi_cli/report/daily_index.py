"""The daily index note: where the day starts. Regenerated from state on every run."""

import re
from datetime import date
from pathlib import Path

from esbi_cli import lang
from esbi_cli.extract import is_url
from esbi_cli.links import link_targets
from esbi_cli.queue import Queue, normalize_target
from esbi_cli.runlog import RunLog
from esbi_cli.vault import Page, Vault, fold


def _sources_where(vault: Vault, key: str, today: date) -> list[Page]:
    found = [p for p in vault.iter_pages(("sources",)) if p.meta.get(key) == today.isoformat()]
    return sorted(found, key=lambda p: fold(p.title))


def _read_section(vault: Vault, today: date) -> list[str]:
    pages = _sources_where(vault, "read", today)
    if not pages:
        return [lang.t(vault.language, "nothing_read")]
    return [f"- [[{p.title}]] — {p.meta.get('summary', '')}" for p in pages]


def _processed_section(vault: Vault, today: date) -> list[str]:
    lines = []
    for page in _sources_where(vault, "processed", today):
        box = "x" if page.meta.get("status") == "read" else " "
        lines.append(f"- [{box}] [[{page.title}]] — {page.meta.get('summary', '')}")
    return lines or [lang.t(vault.language, "nothing_processed")]


QUEUE_LIST_LIMIT = 20


def _short(target: str) -> str:
    return target if is_url(target) else Path(target).name


def _name(item) -> str:
    """The most readable name we have: the label (clip title), else the URL or file name."""
    return item.label or _short(item.target)


def _pending(vault: Vault, queue: Queue) -> list:
    """Queued items not already in the wiki: those are skipped at run time with no model call."""
    known = {
        normalize_target(str(p.meta["url"]))
        for p in vault.iter_pages(("sources",))
        if p.meta.get("url")
    }
    return [i for i in queue.items("queued") if normalize_target(i.target) not in known]


def _queue_section(vault: Vault, queue: Queue) -> list[str]:
    items = _pending(vault, queue)
    L = vault.language
    if not items:
        return [lang.t(L, "queue_empty")]
    total = len(items)
    header = lang.t(L, "queue_one" if total == 1 else "queue_many", n=total)
    if total > QUEUE_LIST_LIMIT:
        header += lang.t(L, "queue_cap", n=QUEUE_LIST_LIMIT)
    names = [_name(i) for i in items]
    return [header + ".", *(f"- {n}" for n in names[:QUEUE_LIST_LIMIT])]


def _review_section(vault: Vault, queue: Queue) -> list[str]:
    notes = sorted((vault.wiki / "review").glob("*.md"))
    L = vault.language
    lines = []
    runs = RunLog(vault.root / ".esbi" / "runs.jsonl").runs()
    if runs and runs[-1].stopped_by == "llm_unavailable":  # the outage is the news of the morning
        waiting = len(_pending(vault, queue))
        key = "llm_down_one" if waiting == 1 else "llm_down_many"
        lines.append(lang.t(L, key, at=f"{runs[-1].started:%Y-%m-%d %H:%M}", n=waiting))
    lines += [f"- [[{n.stem}]]" for n in notes]
    lines += [
        lang.t(L, "could_not_process", name=_name(i), error=i.error) for i in queue.items("failed")
    ]
    lines += [
        lang.t(L, "retrying", name=_name(i), n=i.attempts, max=queue.max_attempts, error=i.error)
        for i in queue.items("queued")
        if i.attempts
    ]
    return lines or [lang.t(L, "nothing_pending")]


REVISIT_COUNT = 3


def _revisit_section(vault: Vault, today: date) -> list[str]:
    """A few older pages, rotating with the date so each day surfaces different ones."""
    older = [
        p
        for p in vault.iter_pages()
        if str(p.meta.get("processed") or p.meta.get("updated") or "") < today.isoformat()
    ]
    if not older:
        return [lang.t(vault.language, "no_old_notes")]
    older.sort(key=lambda p: (p.kind, fold(p.title)))
    start = (today.toordinal() * REVISIT_COUNT) % len(older)
    picked = [older[(start + k) % len(older)] for k in range(min(REVISIT_COUNT, len(older)))]
    return [f"- [[{p.title}]] — {p.meta.get('summary', '')}" for p in picked]


def _orphans(pages: list[Page]) -> int:
    """Pages that no other page links to."""
    linked: set[str] = set()
    for page in pages:
        own = fold(page.title)
        linked |= {fold(t) for t in link_targets(page.body)} - {own}
    return sum(fold(p.title) not in linked for p in pages)


def _stats_section(vault: Vault, today: date) -> list[str]:
    pages = list(vault.iter_pages())
    by_kind = {k: [p for p in pages if p.kind == k] for k in ("sources", "concepts", "entities")}
    sources = by_kind["sources"]
    day = today.isoformat()
    touched = [p for p in by_kind["concepts"] + by_kind["entities"] if p.meta.get("updated") == day]
    read = sum(p.meta.get("status") == "read" for p in sources)
    L = vault.language
    return [
        lang.t(
            L,
            "stat_pages",
            total=len(pages),
            sources=len(sources),
            concepts=len(by_kind["concepts"]),
            entities=len(by_kind["entities"]),
        ),
        lang.t(
            L,
            "stat_today",
            processed=sum(p.meta.get("processed") == day for p in sources),
            touched=len(touched),
        ),
        lang.t(L, "stat_read", read=read, total=len(sources)),
        lang.t(L, "stat_orphans", n=_orphans(pages)),
    ]


STOP_REASONS = {  # RunRecord.stopped_by -> label key
    "max_sources": "stop_max_sources",
    "token_budget": "stop_token_budget",    "llm_unavailable": "stop_llm_unavailable",
}


def _runs_section(vault: Vault, today: date) -> list[str]:
    runs = [
        r for r in RunLog(vault.root / ".esbi" / "runs.jsonl").runs() if r.started.date() == today
    ]
    L = vault.language
    if not runs:
        return [lang.t(L, "no_runs")]
    lines = []
    for run in runs:
        minutes = int((run.finished - run.started).total_seconds() // 60)
        line = lang.t(
            L,
            "run_line",
            at=f"{run.started:%H:%M}",
            manual=lang.t(L, "run_manual") if run.trigger == "manual" else "",
            ingested=run.ingested,
            skipped=run.skipped,
            failed=run.failed,
            tokens=run.tokens_used,
            duration=lang.t(L, "run_minutes", n=minutes)
            if minutes
            else lang.t(L, "run_under_minute"),
        )
        if run.stopped_by:
            key = STOP_REASONS.get(run.stopped_by)
            line += lang.t(L, "run_stopped", reason=lang.t(L, key) if key else run.stopped_by)
        lines.append(line)
    return lines


HOME_START, HOME_END = "<!-- esbi:start -->", "<!-- esbi:end -->"


def _update_home(vault: Vault, queue: Queue, today: date) -> None:
    """Rewrite only the worker-managed block of Home.md; the rest of the page stays the user's."""
    unread = sum(p.meta.get("status") == "processed" for p in vault.iter_pages(("sources",)))
    L = vault.language
    block = "\n".join(
        [
            HOME_START,
            lang.t(L, "home_today", link=f"[[{today.isoformat()}]]"),
            lang.t(L, "home_unread", n=unread),
            lang.t(L, "home_queue", n=len(_pending(vault, queue))),
            HOME_END,
        ]
    )
    home = vault.root / "Home.md"
    text = home.read_text(encoding="utf-8") if home.exists() else "# esbi-cli\n"
    text = text.replace("<!-- second-brain:start -->", HOME_START).replace(  # legacy markers
        "<!-- second-brain:end -->", HOME_END
    )
    pattern = re.compile(re.escape(HOME_START) + r".*?" + re.escape(HOME_END), re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    home.write_text(text, encoding="utf-8")


def build_daily_index(vault: Vault, queue: Queue, today: date) -> Path:
    L = vault.language
    body = [
        f"# {lang.t(L, 'daily_title', date=today.isoformat())}",
        "",
        f"## {lang.t(L, 'daily_read')}",
        *_read_section(vault, today),
        "",
        f"## {lang.t(L, 'daily_processed')}",
        *_processed_section(vault, today),
        "",
        f"## {lang.t(L, 'daily_queue')}",
        *_queue_section(vault, queue),
        "",
        f"## {lang.t(L, 'daily_review')}",
        *_review_section(vault, queue),
        "",
        f"## {lang.t(L, 'daily_revisit')}",
        *_revisit_section(vault, today),
        "",
        f"## {lang.t(L, 'daily_runs')}",
        *_runs_section(vault, today),
        "",
        f"## {lang.t(L, 'daily_stats')}",
        *_stats_section(vault, today),
    ]
    path = vault.wiki / "daily" / f"{today.isoformat()}.md"
    vault.write_page(Page(path, {"type": "daily", "date": today.isoformat()}, "\n".join(body)))
    _update_home(vault, queue, today)
    return path
