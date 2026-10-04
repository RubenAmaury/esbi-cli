"""`codex-cli/<model>`: the official `codex exec`.

UNTESTED AGAINST THE REAL TOOL (the maintainer has no OpenAI account): everything here runs against
a fake `subprocess.run` or a stand-in executable. The argv and the event shapes come from OpenAI's
documentation and repository (see the docstring of `CodexCliLLM`).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from esbi_cli.config import LLMConfig
from esbi_cli.llm import adapter
from esbi_cli.llm.adapter import LLMError, make_llm

SCHEMA = {"type": "object"}


def events_for(text='{"title":"x"}', usage=None):
    usage = usage or {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20}
    return [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": usage},
    ]


def codex_run(seen: list, *, answer='{"title":"x"}', events=None, returncode=0, stderr=""):
    """Stands in for subprocess.run: records the call, then behaves like `codex exec --json -o`:
    JSON Lines on stdout and the final message in the file named by `-o`."""
    events = events_for(answer) if events is None else events

    def run(cmd, **kwargs):
        schema_file, answer_file = cmd[cmd.index("--output-schema") + 1], cmd[cmd.index("-o") + 1]
        seen.append({"cmd": cmd, "schema": json.loads(Path(schema_file).read_text()), **kwargs})
        if answer is not None:
            Path(answer_file).write_text(answer)
        out = "\n".join(["not json: a progress line", *map(json.dumps, events)])
        return subprocess.CompletedProcess(cmd, returncode, out, stderr)

    return run


def codex(model="codex-cli/default", **kw):
    return make_llm(LLMConfig(model=model, **kw))


def test_it_runs_the_official_tool_read_only_and_with_everything_extra_switched_off(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.subprocess, "run", codex_run(seen, answer='{"title":"hola"}'))
    llm = codex(timeout_seconds=42)

    out = llm.complete_json(system="Sé breve.", user="Dame el JSON.", schema=SCHEMA)

    assert out == '{"title":"hola"}'
    call = seen[0]
    cmd = call["cmd"]
    assert isinstance(cmd, list) and not call.get("shell")  # an argv, never a shell string
    assert call["input"] == "Sé breve.\n\nDame el JSON."  # source text on stdin, not in argv
    assert not any("Dame el JSON" in part or "Sé breve" in part for part in cmd)
    assert call["timeout"] == 42
    assert "second-brain" not in call["cwd"]  # a scratch dir, never the project
    # the whole argv, so that dropping any flag (sandbox, tools, user config...) fails this test
    schema_file, answer_file = cmd[cmd.index("--output-schema") + 1], cmd[cmd.index("-o") + 1]
    assert cmd == [
        "codex", "exec", "--json", "--output-schema", schema_file, "-o", answer_file,
        "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "--color", "never",
        "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
        "-c", "project_doc_max_bytes=0",
        "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "apps",
        "--disable", "plugins", "--disable", "hooks", "--disable", "multi_agent",
        "--disable", "computer_use", "--disable", "browser_use",
        "--disable", "image_generation",
        "-",
    ]  # fmt: skip
    assert llm.tokens_used == 120  # input + output; the cached part is already inside input


def test_it_asks_for_the_schema_in_openai_strict_form_without_touching_the_callers(monkeypatch):
    from esbi_cli.llm.schemas import EditPlan

    seen: list = []
    monkeypatch.setattr(adapter.subprocess, "run", codex_run(seen))
    original = EditPlan.model_json_schema()

    codex().complete_json(system="s", user="u", schema=EditPlan.model_json_schema())

    sent = seen[0]["schema"]

    def walk(node):
        if isinstance(node, list):
            for item in node:
                yield from walk(item)
        elif isinstance(node, dict):
            yield node
            for value in node.values():
                yield from walk(value)

    objects = [n for n in walk(sent) if "properties" in n and n.get("type") == "object"]
    assert objects
    for obj in objects:  # strict mode: every field required, nothing else allowed
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])
    for node in walk(sent):  # keywords the worker re-checks itself, and strict mode may reject
        assert not {"default", "minLength", "maxLength", "minItems", "maxItems"} & node.keys()
    assert "title" in sent["properties"]  # a field called like a dropped keyword stays
    assert EditPlan.model_json_schema() == original


def test_it_names_the_model_only_when_one_is_given(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.subprocess, "run", codex_run(seen))

    codex("codex-cli/default").complete_json(system="s", user="u", schema=SCHEMA)
    codex("codex-cli/gpt-5.2-codex").complete_json(system="s", user="u", schema=SCHEMA)

    assert "-m" not in seen[0]["cmd"]
    assert seen[1]["cmd"][seen[1]["cmd"].index("-m") + 1] == "gpt-5.2-codex"


def test_it_estimates_tokens_from_characters_when_the_tool_reports_none(monkeypatch):
    events = events_for()[:-1]  # no turn.completed
    monkeypatch.setattr(adapter.subprocess, "run", codex_run([], answer="a" * 40, events=events))
    llm = codex()

    llm.complete_json(system="s" * 30, user="u" * 30, schema=SCHEMA)

    assert llm.tokens_used == (30 + 2 + 30 + 40) // adapter.CHARS_PER_TOKEN  # prompt + answer


def test_it_does_not_depend_on_the_event_stream_for_the_answer(monkeypatch):
    # the JSON event schema is not versioned (it changed in 0.144): only usage and errors read it
    odd = [{"type": "something.new", "payload": {"text": "ignored"}}, ["not", "an", "event"]]
    monkeypatch.setattr(adapter.subprocess, "run", codex_run([], answer='{"ok":1}', events=odd))

    assert codex().complete_json(system="s", user="u", schema=SCHEMA) == '{"ok":1}'


@pytest.mark.parametrize(
    "kwargs, words",
    [
        (
            {
                "events": [
                    {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}
                ]
            },
            "usage limit",
        ),
        ({"events": [{"type": "error", "message": "401 Unauthorized"}]}, "codex login"),
        (
            {"events": [{"type": "turn.failed", "error": {"message": "Please log in again"}}]},
            "codex login",
        ),
        ({"events": [], "stderr": "Error: Unknown feature flag: shell_tool"}, "Unknown feature"),
        ({"events": [], "stderr": "Not logged in"}, "codex login"),
    ],
)
def test_failures_stop_the_run_with_the_reason(monkeypatch, kwargs, words):
    kwargs = {"answer": None, "returncode": 1, **kwargs}
    monkeypatch.setattr(adapter.subprocess, "run", codex_run([], **kwargs))

    with pytest.raises(LLMError, match=words) as error:
        codex().complete_json(system="s", user="u", schema=SCHEMA)

    assert not isinstance(error.value, adapter.LLMTimeout)  # the account is the problem


def test_exit_zero_without_an_answer_is_an_error_not_an_empty_plan(monkeypatch):
    monkeypatch.setattr(adapter.subprocess, "run", codex_run([], answer=None, returncode=0))

    with pytest.raises(LLMError, match="no answer"):
        codex().complete_json(system="s", user="u", schema=SCHEMA)


def test_reconnecting_notices_are_ignored_when_the_turn_succeeds(monkeypatch):
    events = [{"type": "error", "message": "Reconnecting... 1/5"}, *events_for()]
    monkeypatch.setattr(adapter.subprocess, "run", codex_run([], events=events))

    assert codex().complete_json(system="s", user="u", schema=SCHEMA) == '{"title":"x"}'


def test_a_missing_or_too_slow_tool_is_reported_not_crashed(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError("codex")

    monkeypatch.setattr(adapter.subprocess, "run", missing)
    with pytest.raises(LLMError, match="not installed"):
        codex().complete_json(system="s", user="u", schema=SCHEMA)

    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(adapter.subprocess, "run", slow)
    with pytest.raises(adapter.LLMTimeout):
        codex().complete_json(system="s", user="u", schema=SCHEMA)


def test_a_fallback_takes_over_when_the_account_is_out_of_reach_but_a_timeout_is_not_hidden(
    monkeypatch,
):
    limit = [{"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}]
    monkeypatch.setattr(
        adapter.subprocess, "run", codex_run([], answer=None, events=limit, returncode=1)
    )
    posts: list = []
    reply = {"message": {"content": '{"from": "local"}'}, "prompt_eval_count": 5, "eval_count": 7}

    def post(url, headers, json, timeout):  # noqa: A002 - mirrors httpx.post
        posts.append(json)
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(adapter.httpx, "post", post)
    llm = codex(fallback="ollama/llama3.2:latest")

    assert llm.complete_json(system="s", user="u", schema=SCHEMA) == '{"from": "local"}'
    assert len(posts) == 1

    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(adapter.subprocess, "run", slow)
    with pytest.raises(adapter.LLMTimeout):
        llm.complete_json(system="s", user="u", schema=SCHEMA)
    assert len(posts) == 1


def test_it_says_it_sends_text_out_with_or_without_a_local_fallback():
    assert codex().sends_text_out is True
    assert codex(fallback="ollama/llama3.2").sends_text_out is True


@pytest.mark.parametrize(
    "which, returncode, expected",
    [
        ("/usr/local/bin/codex", 0, "ChatGPT plan"),
        ("/usr/local/bin/codex", 1, "codex login"),
        (None, 0, "not installed"),
    ],
)
def test_doctor_needs_the_codex_tool_installed_and_logged_in(
    tmp_path, vault, config_file, monkeypatch, which, returncode, expected
):
    from test_doctor import doc, healthy

    from esbi_cli import doctor

    healthy(monkeypatch, vault)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: which if name == "codex" else None)
    asked: list = []

    def status(cmd, **kwargs):  # `codex login status` prints to stderr and says it in the exit code
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, "", "Logged in using ChatGPT")

    monkeypatch.setattr(doctor.subprocess, "run", status)
    sub = tmp_path / "sub.toml"
    sub.write_text(config_file.read_text().replace("ollama/fake", "codex-cli/default"))

    result = doc(sub)

    assert expected in result.stdout
    assert ("FAIL model summarize" in result.stdout) == (expected != "ChatGPT plan")
    assert asked in ([], [["codex", "login", "status"]])  # the exact, read-only status command


def test_an_email_is_never_shown_to_the_codex_model(vault, cfg, monkeypatch):
    """Privacy generalises by the `sends_text_out` flag: the real class is refused email."""
    from conftest import FakeLLM, make_plan
    from test_privacy import email_doc, run

    from esbi_cli.privacy import PrivacyError

    def no_call(*args, **kwargs):
        raise AssertionError("codex must not be run for an email")

    monkeypatch.setattr(adapter.subprocess, "run", no_call)

    with pytest.raises(PrivacyError, match=r"\[llm.private\]"):
        run(vault, cfg, email_doc(), codex())

    local = FakeLLM(make_plan(title="Asunto privado"))  # the private model takes it instead
    assert run(vault, cfg, email_doc(), codex(), private_llm=local).status == "ingested"


def test_it_really_spawns_the_tool_with_the_prompt_on_stdin_and_reads_its_files(
    tmp_path, monkeypatch
):
    """No fake of subprocess.run: a stand-in `codex` executable on PATH is run for real."""
    stub = tmp_path / "bin" / "codex"
    stub.parent.mkdir()
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "argv = sys.argv\n"
        "prompt = sys.stdin.read()\n"
        "schema = json.load(open(argv[argv.index('--output-schema') + 1]))\n"
        "answer = json.dumps({'echo': prompt, 'kind': schema['type']})\n"
        "open(argv[argv.index('-o') + 1], 'w').write(answer)\n"
        "usage = {'input_tokens': 3, 'output_tokens': 4}\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': usage}))\n"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")
    llm = codex()

    out = json.loads(llm.complete_json(system="sys", user="usr", schema=SCHEMA))

    assert out == {"echo": "sys\n\nusr", "kind": "object"} and llm.tokens_used == 7
