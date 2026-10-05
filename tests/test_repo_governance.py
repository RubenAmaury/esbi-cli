"""The repository's own rules: what CI runs, how actions are pinned, and what must never be committed."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.M)


def _workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _triggers(workflow):
    return workflow.get("on") or workflow.get(True)  # YAML reads a bare `on` as the boolean True


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_commit_sha(path):
    for ref in USES.findall(path.read_text(encoding="utf-8")):
        assert re.search(r"@[0-9a-f]{40}$", ref), f"{path.name}: {ref} is not pinned by SHA"


def test_ci_also_runs_on_the_testing_branch():
    assert "testing" in _triggers(_workflow("ci.yml"))["push"]["branches"]


def test_code_scanning_runs_on_pull_requests_pushes_and_a_weekly_schedule():
    triggers = _triggers(_workflow("codeql.yml"))
    assert "pull_request" in triggers and triggers["push"]["branches"] == ["main"]
    assert triggers["schedule"]
    languages = _workflow("codeql.yml")["jobs"]["analyze"]["strategy"]["matrix"]["language"]
    assert set(languages) == {"python", "actions"}


def test_dependency_review_fails_a_pull_request_on_a_high_severity_finding():
    job = _workflow("dependency-review.yml")["jobs"]["dependency-review"]
    review = next(s for s in job["steps"] if "dependency-review-action" in s.get("uses", ""))
    assert review["with"]["fail-on-severity"] == "high"
    assert "pull_request" in _triggers(_workflow("dependency-review.yml"))


def test_no_file_meant_for_an_agent_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split("\n")
    if not tracked or not tracked[0]:
        pytest.skip("not a git checkout")
    private = {"AGENTS.md", "CLAUDE.md", "BACKLOG.md"}
    found = [
        f for f in tracked if f.split("/")[-1] in private or f.startswith((".claude/", ".kilo/"))
    ]
    assert found == []


def test_the_documentation_sources_are_not_tracked_only_the_built_site_is_published():
    """The docs are written and built on the maintainer's machine; only the built site is uploaded
    (to the branch GitHub Pages serves). So no source page, config or docs workflow lives here."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split("\n")
    if not tracked or not tracked[0]:
        pytest.skip("not a git checkout")
    found = [
        f
        for f in tracked
        if f.startswith("docs/") or f in {"mkdocs.yml", ".github/workflows/pages.yml"}
    ]
    assert found == []


def test_every_statement_of_the_supported_platform_says_macos_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    landing = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "macOS is the only supported platform" in readme
    assert "Linux works" not in readme and "source checkout, Linux" not in readme
    assert "macOS and Linux" not in landing and "macOS &middot; then run" in landing
    assert "Operating System :: MacOS" in pyproject and "Linux" not in pyproject
