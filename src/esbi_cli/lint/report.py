"""Write the lint findings to wiki/review/Lint.md (only while there is something to fix)."""

from datetime import date
from pathlib import Path

from esbi_cli import lang
from esbi_cli.lint.checks import Issue, LintReport
from esbi_cli.vault import Page, Vault

KINDS = (
    "orphan",
    "broken-link",
    "missing-field",
    "unlinked-mention",
    "near-duplicate",
    "missing-concept",
)
MAX_PER_SECTION = 50


def _line(issue: Issue, language: str) -> str:
    match issue.kind:
        case "orphan":
            return f"- [[{issue.page}]]"
        case "broken-link":
            return f"- [[{issue.page}]] → `{issue.detail}`"  # code span: no ghost link in the graph
        case "missing-field":
            return lang.t(language, "lint_missing_field_line", page=issue.page, field=issue.detail)
        case "unlinked-mention":
            return lang.t(language, "lint_unlinked_line", page=issue.page, target=issue.detail)
        case "missing-concept":
            sources = ", ".join(f"[[{t}]]" for t in issue.detail.split(", "))
            return lang.t(language, "lint_missing_concept_line", name=issue.page, sources=sources)
        case _:
            return f"- [[{issue.page}]] ≈ [[{issue.detail}]]"


def write_lint_report(vault: Vault, report: LintReport, today: date) -> Path | None:
    path = vault.wiki / "review" / "Lint.md"
    if not report.issues:
        path.unlink(missing_ok=True)
        return None
    L = vault.language
    body = [f"# {lang.t(L, 'lint_title', date=today.isoformat())}", ""]
    for kind in KINDS:
        found = [i for i in report.issues if i.kind == kind]
        if not found:
            continue
        body += [
            f"## {lang.t(L, 'lint_' + kind.replace('-', '_'))}",
            *(_line(i, L) for i in found[:MAX_PER_SECTION]),
        ]
        if len(found) > MAX_PER_SECTION:
            body.append(lang.t(L, "lint_more", n=len(found) - MAX_PER_SECTION))
        body.append("")
    body.append(lang.t(L, "lint_footer"))
    vault.write_page(
        Page(path, {"type": "review", "kind": "lint", "date": today.isoformat()}, "\n".join(body))
    )
    return path
