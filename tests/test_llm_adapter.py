import base64
import json
import subprocess

import httpx
import pytest

from esbi_cli.config import LLMConfig
from esbi_cli.llm import adapter
from esbi_cli.llm.adapter import LLMError, make_llm

SCHEMA = {"type": "object"}


def fake_post(response: dict, seen: list):
    def post(url, headers, json, timeout):  # noqa: A002 - mirrors httpx.post
        seen.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(200, json=response, request=httpx.Request("POST", url))

    return post


def test_make_llm_rejects_bad_specs():
    with pytest.raises(ValueError):
        make_llm(LLMConfig(model="llama3"))
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        make_llm(LLMConfig(model="foo/bar"))


def test_ollama_sends_schema_and_context_window(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"message": {"content": "{}"}}, seen))
    out = make_llm(LLMConfig(model="ollama/llama3.2:latest", num_ctx=4096)).complete_json(
        system="s", user="u", schema=SCHEMA
    )
    assert out == "{}"
    assert seen[0]["url"] == "http://localhost:11434/api/chat"
    assert seen[0]["json"]["format"] == SCHEMA and seen[0]["json"]["options"]["num_ctx"] == 4096
    assert seen[0]["json"]["model"] == "llama3.2:latest"


def test_ollama_caps_the_answer_length_only_when_asked_to(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"message": {"content": "{}"}}, seen))

    make_llm(LLMConfig(model="ollama/m")).complete_json(system="s", user="u", schema=SCHEMA)
    make_llm(LLMConfig(model="ollama/m", max_tokens=1200)).complete_json(
        system="s", user="u", schema=SCHEMA
    )

    assert "num_predict" not in seen[0]["json"]["options"]  # a runaway answer is the opt-in fix
    assert seen[1]["json"]["options"]["num_predict"] == 1200


def test_openai_uses_base_url_and_key_from_env(monkeypatch):
    seen: list = []
    monkeypatch.setenv("MY_KEY", "sk-test")
    resp = {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(adapter.httpx, "post", fake_post(resp, seen))
    cfg = LLMConfig(model="openai/gpt-x", base_url="http://localhost:1234/v1", api_key_env="MY_KEY")
    make_llm(cfg).complete_json(system="s", user="u", schema=SCHEMA)
    assert seen[0]["url"] == "http://localhost:1234/v1/chat/completions"
    assert seen[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_anthropic_forces_tool_and_returns_its_input(monkeypatch):
    seen: list = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    resp = {"content": [{"type": "tool_use", "input": {"title": "t"}}]}
    monkeypatch.setattr(adapter.httpx, "post", fake_post(resp, seen))
    out = make_llm(LLMConfig(model="anthropic/claude-x")).complete_json(
        system="s", user="u", schema=SCHEMA
    )
    assert json.loads(out) == {"title": "t"}
    assert seen[0]["json"]["tool_choice"] == {"type": "tool", "name": "submit_edit_plan"}
    assert seen[0]["headers"]["x-api-key"] == "k"


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        make_llm(LLMConfig(model="anthropic/claude-x")).complete_json(
            system="s", user="u", schema=SCHEMA
        )


@pytest.mark.parametrize(
    ("model", "response"),
    [
        (
            "ollama/m",
            {"message": {"content": "{}"}, "prompt_eval_count": 100, "eval_count": 20},
        ),
        (
            "openai/m",
            {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        ),
        (
            "anthropic/m",
            {
                "content": [{"type": "tool_use", "input": {}}],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        ),
    ],
)
def test_every_backend_accumulates_token_usage_across_calls(monkeypatch, model, response):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(adapter.httpx, "post", fake_post(response, []))
    llm = make_llm(LLMConfig(model=model))
    assert llm.tokens_used == 0
    llm.complete_json(system="s", user="u", schema=SCHEMA)
    llm.complete_json(system="s", user="u", schema=SCHEMA)
    assert llm.tokens_used == 240


def test_a_response_without_usage_counts_as_zero_tokens(monkeypatch):
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"message": {"content": "{}"}}, []))
    llm = make_llm(LLMConfig(model="ollama/m"))
    llm.complete_json(system="s", user="u", schema=SCHEMA)
    assert llm.tokens_used == 0


def cli_run(stdout: str, seen: list, returncode: int = 0):
    """Stands in for subprocess.run: records the call, answers like `claude -p --output-format json`."""

    def run(cmd, **kwargs):
        seen.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    return run


def cli_answer(**fields):
    return json.dumps(
        {
            "is_error": False,
            "result": '{"title":"x"}',
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 700, "output_tokens": 73},
            **fields,
        }
    )


def test_claude_cli_runs_the_official_tool_with_everything_extra_switched_off(monkeypatch):
    seen: list = []
    reply = cli_answer(structured_output={"title": "hola", "n": 2})
    monkeypatch.setattr(adapter.subprocess, "run", cli_run(reply, seen))
    llm = make_llm(LLMConfig(model="claude-cli/default"))

    out = llm.complete_json(system="Sé breve.", user="Dame el JSON.", schema=SCHEMA)

    assert json.loads(out) == {"title": "hola", "n": 2}  # the structured answer, not the text
    call = seen[0]
    assert call["input"] == "Dame el JSON."  # the source text travels on stdin, never in argv
    cmd = call["cmd"]
    assert cmd[:2] == ["claude", "-p"] and "--model" not in cmd  # "default" = the account's own
    # Measured: without these, every call carried ~450,000 tokens of the user's tools and plugins
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--setting-sources") + 1] == ""
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert cmd[cmd.index("--system-prompt") + 1] == "Sé breve."
    assert llm.tokens_used == 775  # input, cache and output all count against the subscription


def test_claude_cli_names_the_model_when_one_is_given_and_falls_back_to_the_text(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.subprocess, "run", cli_run(cli_answer(), seen))

    out = make_llm(LLMConfig(model="claude-cli/sonnet")).complete_json(
        system="s", user="u", schema=SCHEMA
    )

    assert seen[0]["cmd"][seen[0]["cmd"].index("--model") + 1] == "sonnet"
    assert out == '{"title":"x"}'


@pytest.mark.parametrize(
    "result, words",
    [
        ("Failed to authenticate: OAuth session expired", "claude auth login"),
        ("You've hit your usage limit. Resets at 5pm", "usage limit"),
    ],
)
def test_claude_cli_failures_stop_the_run_with_the_reason(monkeypatch, result, words):
    reply = cli_answer(is_error=True, result=result)
    monkeypatch.setattr(adapter.subprocess, "run", cli_run(reply, []))

    with pytest.raises(LLMError, match=words) as error:
        make_llm(LLMConfig(model="claude-cli/default")).complete_json(
            system="s", user="u", schema=SCHEMA
        )

    assert not isinstance(
        error.value, adapter.LLMTimeout
    )  # the account is the problem, not the input


def test_claude_cli_that_is_missing_or_too_slow_is_reported_not_crashed(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(adapter.subprocess, "run", missing)
    llm = make_llm(LLMConfig(model="claude-cli/default"))
    with pytest.raises(LLMError, match="not installed"):
        llm.complete_json(system="s", user="u", schema=SCHEMA)

    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(adapter.subprocess, "run", slow)
    with pytest.raises(adapter.LLMTimeout):
        llm.complete_json(system="s", user="u", schema=SCHEMA)


def test_a_fallback_model_takes_over_when_the_primary_is_out_of_reach_but_not_on_success(
    monkeypatch,
):
    limit = cli_answer(is_error=True, result="You've hit your usage limit.")
    runs: list = []
    monkeypatch.setattr(adapter.subprocess, "run", cli_run(limit, runs))
    posts: list = []
    reply = {"message": {"content": '{"from": "local"}'}, "prompt_eval_count": 5, "eval_count": 7}
    monkeypatch.setattr(adapter.httpx, "post", fake_post(reply, posts))
    llm = make_llm(LLMConfig(model="claude-cli/default", fallback="ollama/llama3.2:latest"))

    out = llm.complete_json(system="s", user="u", schema=SCHEMA)

    assert out == '{"from": "local"}' and len(runs) == 1 and len(posts) == 1
    assert posts[0]["json"]["model"] == "llama3.2:latest"
    assert llm.tokens_used == 775 + 12  # what both models used counts toward the budget

    ok = cli_answer(structured_output={"from": "claude"})
    monkeypatch.setattr(adapter.subprocess, "run", cli_run(ok, []))
    assert json.loads(llm.complete_json(system="s", user="u", schema=SCHEMA)) == {"from": "claude"}
    assert len(posts) == 1  # the fallback was not touched while the primary worked


def test_a_timeout_of_the_primary_is_not_hidden_by_the_fallback(monkeypatch):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(adapter.subprocess, "run", slow)
    llm = make_llm(LLMConfig(model="claude-cli/default", fallback="ollama/llama3.2:latest"))

    with pytest.raises(adapter.LLMTimeout):
        llm.complete_json(system="s", user="u", schema=SCHEMA)


def test_models_run_by_someone_else_say_so_and_a_local_one_does_not():
    assert make_llm(LLMConfig(model="claude-cli/default")).sends_text_out is True
    assert make_llm(LLMConfig(model="openai/gpt-x")).sends_text_out is True
    assert make_llm(LLMConfig(model="anthropic/claude-x")).sends_text_out is True
    assert make_llm(LLMConfig(model="ollama/llama3.2")).sends_text_out is False
    both = make_llm(LLMConfig(model="claude-cli/default", fallback="ollama/llama3.2"))
    assert both.sends_text_out is True  # the primary sees the text first


def test_lm_studio_is_a_local_openai_compatible_server_that_needs_no_key(monkeypatch):
    seen: list = []
    reply = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 6},
    }
    monkeypatch.setattr(adapter.httpx, "post", fake_post(reply, seen))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = make_llm(LLMConfig(model="lmstudio/qwen2.5-7b-instruct"))

    out = llm.complete_json(system="s", user="u", schema=SCHEMA)

    assert out == '{"ok": true}' and llm.tokens_used == 10
    assert seen[0]["url"] == "http://localhost:1234/v1/chat/completions"  # LM Studio's default port
    assert "Authorization" not in seen[0]["headers"]
    assert seen[0]["json"]["model"] == "qwen2.5-7b-instruct"
    assert seen[0]["json"]["response_format"]["type"] == "json_schema"  # the answer is constrained
    assert llm.sends_text_out is False  # it runs on this machine


def test_lm_studio_on_another_port_or_machine_uses_base_url(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        adapter.httpx, "post", fake_post({"choices": [{"message": {"content": "{}"}}]}, seen)
    )

    make_llm(LLMConfig(model="lmstudio/m", base_url="http://192.168.1.5:5000/v1")).complete_json(
        system="s", user="u", schema=SCHEMA
    )

    assert seen[0]["url"] == "http://192.168.1.5:5000/v1/chat/completions"


def test_ollama_reads_the_text_of_an_image_with_a_vision_model(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        adapter.httpx, "post", fake_post({"message": {"content": " Hola \n"}}, seen)
    )
    ocr = adapter.make_ocr(LLMConfig(model="ollama/qwen3-vl:2b-instruct", num_ctx=4096))

    assert ocr.read_image(b"PNGDATA") == "Hola"

    sent = seen[0]["json"]
    assert seen[0]["url"] == "http://localhost:11434/api/chat"
    assert sent["messages"][0]["images"] == [base64.b64encode(b"PNGDATA").decode()]
    assert "format" not in sent and sent["options"]["temperature"] == 0
    assert sent["options"]["num_ctx"] == 4096


@pytest.mark.parametrize(
    "cfg",
    [
        LLMConfig(model="openai/gpt-x"),  # only Ollama serves images here
        LLMConfig(model="ollama/m", base_url="http://other-host:11434"),  # images never leave
        LLMConfig(model="ollama/m-cloud"),
        LLMConfig(model="ollama/m", fallback="openai/gpt-x"),
    ],
)
def test_the_ocr_model_must_be_a_local_ollama_model(cfg):
    with pytest.raises(ValueError, match=r"\[llm\.ocr\]"):
        adapter.make_ocr(cfg)
