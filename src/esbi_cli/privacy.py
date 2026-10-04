"""Email stays on the machine: it is never sent to a model that sends text away."""

import re
from urllib.parse import urlparse

from esbi_cli import lang
from esbi_cli.llm.adapter import is_loopback
from esbi_cli.vault import Vault


class PrivacyError(ValueError):
    pass


def sends_text_out(llm) -> bool:
    """True for models run by someone else (API, subscription); a local model, and any fake, is not."""
    return bool(getattr(llm, "sends_text_out", False))


def remote_host(model: str, base_url: str | None) -> str | None:
    """The host serving an Ollama or LM Studio model when that is not this machine, else None."""
    if model.partition("/")[0] not in ("ollama", "lmstudio") or not base_url:
        return None
    return None if is_loopback(base_url) else urlparse(base_url).hostname


def remote_warning(model: str, host: str) -> str:
    return (
        f"{model} is served by {host}, not this machine: the text of your notes goes to that "
        "host, and email is kept off it."
    )


def section_pattern(source_title: str) -> re.Pattern:
    """The `## From [[source]]` section a source adds to a concept page, in any catalogued language
    (a vault may hold sections written before the language setting changed)."""
    link = re.escape(f"[[{source_title}]]")
    heads = "|".join(re.escape(h) for h in lang.every("from_source"))
    return re.compile(rf"\n*## (?:{heads}) {link}\n.*?(?=\n## |\Z)", re.DOTALL)


def private_sources(vault: Vault) -> set[str]:
    return {p.title for p in vault.iter_pages(("sources",)) if p.meta.get("kind") == "email"}


def _email_links(vault: Vault) -> set[str]:
    return {f"[[{t}]]" for t in private_sources(vault)}


def private_titles(vault: Vault) -> set[str]:
    """Pages to hide from a cloud model: email sources, pages built only from them, and every
    synthesis that used any email page (its text is an answer written from that page)."""
    emails = private_sources(vault)
    linked = _email_links(vault)
    hidden = set(emails)
    for page in vault.iter_pages(("concepts", "entities", "syntheses")):
        sources = page.meta.get("sources") or []
        if page.kind == "syntheses":
            if any(s in linked for s in sources):
                hidden.add(page.title)
        elif sources and all(s in linked for s in sources):
            hidden.add(page.title)
    return hidden


def email_touched(vault: Vault) -> set[str]:
    """Pages email helped write (some source of theirs is an email): their one-line summaries may
    carry email text, so a cloud model is offered the title only."""
    linked = _email_links(vault)
    return {
        p.title
        for p in vault.iter_pages(("concepts", "entities", "syntheses"))
        if any(s in linked for s in (p.meta.get("sources") or []))
    }


def public_body(body: str, vault_private_sources: set[str]) -> str:
    """A page's text without the sections that came from email."""
    for title in vault_private_sources:
        body = section_pattern(title).sub("", body)
    return body.strip()
