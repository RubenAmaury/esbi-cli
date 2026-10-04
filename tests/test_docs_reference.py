"""The reference pages cover the real CLI and the real config: a new command, option or setting
that is not written up fails here."""

import dataclasses
import re
from pathlib import Path

import typer.main

from esbi_cli.cli import app
from esbi_cli.config import BenchConfig, Config, EmailConfig, LLMConfig

DOCS = Path(__file__).parent.parent / "docs" / "reference"
CLI_PAGE = (DOCS / "cli.md").read_text(encoding="utf-8").splitlines()
CONFIG_PAGE = (DOCS / "configuration.md").read_text(encoding="utf-8")


def leaf_commands(group, prefix=("sb",)):
    for name, command in group.commands.items():
        path = (*prefix, name)
        if hasattr(command, "commands"):
            yield from leaf_commands(command, path)
        else:
            yield " ".join(path), command


def section(title: str) -> str | None:
    """The text under the heading `title` in cli.md, up to the next heading of the same or higher level."""
    for start, line in enumerate(CLI_PAGE):
        m = re.fullmatch(rf"(#{{2,3}}) {re.escape(title)}", line)
        if m:
            level = len(m[1])
            body = []
            for later in CLI_PAGE[start + 1 :]:
                h = re.match(r"(#+) ", later)
                if h and len(h[1]) <= level:
                    break
                body.append(later)
            return "\n".join(body)
    return None


def test_every_command_has_a_section_with_all_its_options():
    missing = []
    for title, command in leaf_commands(typer.main.get_command(app)):
        text = section(title)
        if text is None:
            missing.append(f"no heading '## {title}' in cli.md")
            continue
        for param in command.params:
            for flag in (*param.opts, *getattr(param, "secondary_opts", ())):
                if flag.startswith("--") and flag != "--help" and flag not in text:
                    missing.append(f"{title}: {flag} is not described")
    assert missing == []


def test_the_menu_has_a_section():
    assert section("sb (menu)") is not None


def test_every_config_key_is_documented():
    keys = set()
    for cls in (Config, LLMConfig, EmailConfig, BenchConfig):
        keys |= {f.name for f in dataclasses.fields(cls)}
    keys -= {"llm", "email", "bench"}  # sections: documented as headings
    undocumented = sorted(k for k in keys if f"`{k}`" not in CONFIG_PAGE)
    assert undocumented == []


def test_every_llm_task_is_documented():
    for task in ("summarize", "synthesize", "ask", "private", "ocr", "embed"):
        assert f"[llm.{task}]" in CONFIG_PAGE, task
