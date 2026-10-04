"""The OCR model presets, the machine's RAM, and talking to a local Ollama (a mock transport: no
model, no download)."""

import json

import httpx
import pytest

from esbi_cli import ocr_models
from esbi_cli.ocr_models import (
    DEEPSEEK,
    GENERIC_PROMPT,
    QWEN,
    PullError,
    machine_ram_gb,
    preset,
    prompt_for,
    recommended,
    version_at_least,
)


def ollama(monkeypatch, handler):
    """Every call this module makes to Ollama goes to `handler` instead of the network."""
    monkeypatch.setattr(
        ocr_models, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_each_known_model_has_its_own_prompt_and_any_other_gets_the_generic_one():
    assert prompt_for("deepseek-ocr:3b") == DEEPSEEK.prompt != GENERIC_PROMPT
    assert prompt_for("qwen3-vl:2b-instruct") == QWEN.prompt
    assert prompt_for("llava:7b") == GENERIC_PROMPT
    assert prompt_for("deepseek-ocr") == DEEPSEEK.prompt  # the tag-less name is the same model


def test_deepseek_ocr_is_asked_with_its_own_short_instruction_not_a_general_one():
    # its model card: "Free OCR." (plain text); a long instruction makes it chatty or wrong
    assert DEEPSEEK.prompt == "Free OCR."


def test_presets_state_size_ram_and_the_ollama_version_they_need():
    assert (DEEPSEEK.size_gb, DEEPSEEK.min_ollama) == (6.7, "0.13.0")
    assert QWEN.size_gb == 1.9
    assert DEEPSEEK.min_ram_gb > QWEN.min_ram_gb
    assert preset("qwen3-vl:2b-instruct") is QWEN and preset("llava") is None


def test_the_recommendation_follows_the_machines_memory():
    assert recommended(8) is QWEN and recommended(16) is DEEPSEEK
    assert recommended(None) is QWEN  # unknown memory: the model that fits small machines


def test_ram_is_read_from_the_system_in_gib(monkeypatch):
    sysconf = {"SC_PAGE_SIZE": 16384, "SC_PHYS_PAGES": 524288}  # 8 GiB
    monkeypatch.setattr(ocr_models.os, "sysconf", lambda name: sysconf[name])
    assert machine_ram_gb() == 8.0


def test_ram_is_unknown_where_the_system_does_not_say(monkeypatch):
    def nope(name):
        raise ValueError(name)

    monkeypatch.setattr(ocr_models.os, "sysconf", nope)
    assert machine_ram_gb() is None


@pytest.mark.parametrize(
    "have, need, ok",
    [("0.13.5", "0.13.0", True), ("0.13.0", "0.13.0", True), ("0.12.9", "0.13.0", False),
     ("0.13.5-rc1", "0.13.0", True), ("1.0.0", "0.13.0", True), (None, "0.13.0", True)],
)  # fmt: skip
def test_the_ollama_version_check(have, need, ok):
    assert version_at_least(have, need) is ok  # an unknown version is not a reason to complain


def test_installed_models_and_version_come_from_the_ollama_server(monkeypatch):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3-vl:2b-instruct"}]})
        return httpx.Response(200, json={"version": "0.13.5"})

    ollama(monkeypatch, handler)

    assert ocr_models.installed_models("http://localhost:11434") == {"qwen3-vl:2b-instruct"}
    assert ocr_models.ollama_version("http://localhost:11434") == "0.13.5"


def test_an_ollama_that_is_down_is_none_not_an_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    ollama(monkeypatch, handler)

    assert ocr_models.installed_models("http://localhost:11434") is None
    assert ocr_models.ollama_version("http://localhost:11434") is None


def test_a_model_is_installed_under_its_name_or_its_latest_tag():
    assert ocr_models.is_installed("deepseek-ocr", {"deepseek-ocr:latest"})
    assert ocr_models.is_installed("qwen3-vl:2b-instruct", {"qwen3-vl:2b-instruct"})
    assert not ocr_models.is_installed("qwen3-vl:2b-instruct", {"qwen3-vl:4b-instruct"})


def stream(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_pull_streams_progress_through_ollamas_pull_api(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            content=stream(
                {"status": "pulling manifest"},
                {"status": "pulling abc", "digest": "abc", "total": 100, "completed": 25},
                {"status": "pulling abc", "digest": "abc", "total": 100, "completed": 100},
                {"status": "success"},
            ),
        )

    ollama(monkeypatch, handler)
    progress = []

    ocr_models.pull(
        "http://localhost:11434",
        "deepseek-ocr:3b",
        lambda status, done: progress.append((status, done)),
    )

    assert seen == [("/api/pull", {"model": "deepseek-ocr:3b", "stream": True})]
    assert progress == [
        ("pulling manifest", None),
        ("pulling abc", 0.25),
        ("pulling abc", 1.0),
        ("success", None),
    ]


def test_pull_reports_an_error_line_from_ollama(monkeypatch):
    ollama(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=stream({"error": "pull model manifest: file does not exist"})
        ),
    )

    with pytest.raises(PullError, match="file does not exist"):
        ocr_models.pull("http://localhost:11434", "nope:1b", lambda *_: None)


def test_pull_says_so_when_ollama_is_not_running(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    ollama(monkeypatch, handler)

    with pytest.raises(PullError, match="not reachable"):
        ocr_models.pull("http://localhost:11434", "deepseek-ocr:3b", lambda *_: None)


def test_pull_never_goes_to_a_server_on_another_machine(monkeypatch):
    def handler(request):
        raise AssertionError("must not call a remote server")

    ollama(monkeypatch, handler)

    with pytest.raises(PullError, match="this machine"):
        ocr_models.pull("http://gpu-box.lan:11434", "deepseek-ocr:3b", lambda *_: None)
