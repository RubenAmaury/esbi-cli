"""`sb ocr status|enable|disable` and the OCR questions of `sb init`: a mock Ollama, a fake amount of
memory, throw-away config files. Nothing is downloaded."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from esbi_cli import cli, ocr_models
from esbi_cli.cli import app
from esbi_cli.config import load_config

QWEN = "qwen3-vl:2b-instruct"
DEEPSEEK = "deepseek-ocr:3b"


class Ollama:
    """A fake local Ollama: what it has installed, its version, and every pull it was asked for."""

    def __init__(self, monkeypatch, *, models=(), version="0.13.5", ram=16.0, down=False):
        self.models, self.version, self.down, self.pulls = list(models), version, down, []
        monkeypatch.setattr(
            ocr_models, "_client", lambda: httpx.Client(transport=httpx.MockTransport(self))
        )
        monkeypatch.setattr(ocr_models, "machine_ram_gb", lambda: ram)

    def __call__(self, request):
        if self.down:
            raise httpx.ConnectError("refused")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": self.version})
        assert request.url.path == "/api/pull", request.url
        name = json.loads(request.content)["model"]
        self.pulls.append(name)
        self.models.append(name)
        events = [
            {"status": "pulling manifest"},
            {"status": "pulling abc", "total": 100, "completed": 50},
            {"status": "pulling abc", "total": 100, "completed": 100},
            {"status": "success"},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(e) for e in events) + "\n")


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\nvault = "{tmp_path / "v"}"\n\n[llm.summarize]\nmodel = "ollama/llama3.2:latest"\n'
    )
    return path


def with_ocr(config, model=QWEN, extra=""):
    config.write_text(config.read_text() + f'\n[llm.ocr]\nmodel = "ollama/{model}"\n{extra}')
    return config


def sb(config, *args, input=None):
    return CliRunner().invoke(app, ["ocr", *args, "--config", str(config)], input=input)


# --- status ------------------------------------------------------------------------------------


def test_status_when_images_were_never_set_up_says_how_to(monkeypatch, config):
    Ollama(monkeypatch)

    result = sb(config, "status")

    assert result.exit_code == 0, result.output
    assert "off" in result.stdout and "sb ocr enable" in result.stdout


def test_status_of_an_installed_model_shows_everything_that_matters(monkeypatch, config):
    Ollama(monkeypatch, models=[QWEN], ram=8.0)

    result = sb(with_ocr(config), "status")

    out = result.stdout
    assert "on" in out and QWEN in out and "installed" in out and "not installed" not in out
    assert "1.9 GB" in out  # what it weighs
    assert "8 GB" in out  # this machine's memory
    assert "likely" in out and "0.13.5" in out and "0.12.7" in out  # runs here; Ollama vs needed


def test_status_of_a_missing_model_gives_the_exact_pull_command(monkeypatch, config):
    Ollama(monkeypatch, models=[])

    out = sb(with_ocr(config, DEEPSEEK), "status").stdout

    assert "not installed" in out and f"ollama pull {DEEPSEEK}" in out and "6.7 GB" in out


def test_status_says_when_the_model_is_too_big_for_this_machine(monkeypatch, config):
    Ollama(monkeypatch, models=[DEEPSEEK], ram=8.0)

    out = sb(with_ocr(config, DEEPSEEK), "status").stdout

    assert "may not load" in out and "16 GB" in out


def test_status_says_when_ollama_is_too_old_or_not_running(monkeypatch, config):
    with_ocr(config, DEEPSEEK)
    Ollama(monkeypatch, models=[DEEPSEEK], version="0.12.0")
    assert "upgrade" in sb(config, "status").stdout

    Ollama(monkeypatch, down=True)
    assert "not reachable" in sb(config, "status").stdout


def test_status_of_a_switched_off_section_shows_the_kept_model(monkeypatch, config):
    Ollama(monkeypatch, models=[QWEN])

    out = sb(with_ocr(config, extra="enabled = false\n"), "status").stdout

    assert "off" in out and QWEN in out and "sb ocr enable" in out


# --- enable and disable ------------------------------------------------------------------------


def test_enable_picks_the_model_that_fits_this_machine_and_never_downloads_by_itself(
    monkeypatch, config
):
    server = Ollama(monkeypatch, models=[], ram=8.0)

    result = sb(config, "enable")

    assert result.exit_code == 0, result.output
    assert load_config(config).llm["ocr"].model == f"ollama/{QWEN}" and load_config(config).ocr_on
    assert server.pulls == []  # nothing is fetched without --pull or a yes
    assert f"ollama pull {QWEN}" in result.stdout and "1.9 GB" in result.stdout
    assert str(config) in result.stdout  # what was changed, and where


def test_enable_on_a_big_machine_still_picks_the_small_default_model(monkeypatch, config):
    Ollama(monkeypatch, models=[], ram=32.0)

    sb(config, "enable")

    assert load_config(config).llm["ocr"].model == f"ollama/{QWEN}"  # DeepSeek only on request


def test_enable_with_pull_downloads_the_model_and_shows_progress(monkeypatch, config):
    server = Ollama(monkeypatch, models=[])

    result = sb(config, "enable", "--model", DEEPSEEK, "--pull")

    assert result.exit_code == 0, result.output
    assert server.pulls == [DEEPSEEK]
    assert "pulling abc 50%" in result.stdout and "success" in result.stdout


def test_enable_with_pull_does_not_download_what_is_already_installed(monkeypatch, config):
    server = Ollama(monkeypatch, models=[QWEN])

    result = sb(config, "enable", "--model", QWEN, "--pull")

    assert server.pulls == [] and "already installed" in result.stdout


def test_enable_with_pull_while_ollama_is_down_prints_the_command_instead(monkeypatch, config):
    Ollama(monkeypatch, down=True)

    result = sb(config, "enable", "--model", DEEPSEEK, "--pull")

    assert result.exit_code == 0, result.output
    assert "not reachable" in result.stdout and f"ollama pull {DEEPSEEK}" in result.stdout
    assert load_config(config).ocr_on  # the setting is saved all the same


def test_enable_asks_before_downloading_and_only_a_yes_downloads(monkeypatch, config):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    server = Ollama(monkeypatch, models=[])

    for answer in ("n\n", "\n", "no\n"):  # a no, the bare default, anything but yes
        result = sb(config, "enable", "--model", DEEPSEEK, input=answer)
        assert "Download it now?" in result.stdout and server.pulls == [], answer

    result = sb(config, "enable", "--model", DEEPSEEK, input="y\n")

    assert server.pulls == [DEEPSEEK] and result.exit_code == 0


def test_enable_does_not_ask_when_there_is_nobody_to_ask(monkeypatch, config):
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    server = Ollama(monkeypatch, models=[])

    result = sb(config, "enable", "--model", DEEPSEEK)

    assert "Download it now?" not in result.stdout and server.pulls == []


def test_enable_warns_about_memory_and_an_old_ollama_but_still_enables(monkeypatch, config):
    Ollama(monkeypatch, models=[DEEPSEEK], ram=8.0, version="0.12.0")

    result = sb(config, "enable", "--model", DEEPSEEK)

    assert result.exit_code == 0 and load_config(config).ocr_on
    assert "16 GB" in result.stdout and "may not load" in result.stdout
    assert "upgrade" in result.stdout and "0.13.0" in result.stdout


def test_enable_switches_the_model_and_keeps_every_other_setting(monkeypatch, config):
    Ollama(monkeypatch, models=[DEEPSEEK])
    with_ocr(config, extra="timeout_seconds = 900\n")
    before = config.read_text()

    sb(config, "enable", "--model", DEEPSEEK)

    cfg = load_config(config)
    assert cfg.llm["ocr"].model == f"ollama/{DEEPSEEK}" and cfg.llm["ocr"].timeout_seconds == 900
    assert cfg.llm["summarize"].model == "ollama/llama3.2:latest"
    assert config.read_text().split("[llm.ocr]")[0] == before.split("[llm.ocr]")[0]


def test_enable_turns_a_switched_off_section_back_on_with_its_model(monkeypatch, config):
    Ollama(monkeypatch, models=[QWEN])
    with_ocr(config, extra="enabled = false\n")

    result = sb(config, "enable")

    assert load_config(config).ocr_on and load_config(config).llm["ocr"].model == f"ollama/{QWEN}"
    assert "installed" in result.stdout


def test_enable_replaces_a_model_that_cannot_read_images_here(monkeypatch, config):
    Ollama(monkeypatch, models=[], ram=8.0)
    with_ocr(config, "gpt-x").write_text(config.read_text().replace("ollama/gpt-x", "openai/gpt-x"))

    sb(config, "enable")

    assert load_config(config).llm["ocr"].model == f"ollama/{QWEN}"


@pytest.mark.parametrize("name", ['x"\nvault = "/etc', "a b", "-rf", "", "x;y", "../x"])
def test_enable_refuses_a_model_name_that_is_not_an_ollama_name(monkeypatch, config, name):
    Ollama(monkeypatch)
    before = config.read_text()

    result = sb(config, "enable", "--model", name)

    assert result.exit_code == 1 and "model name" in result.output
    assert config.read_text() == before


def test_enable_accepts_the_name_the_way_the_config_writes_it(monkeypatch, config):
    Ollama(monkeypatch, models=[QWEN])

    sb(config, "enable", "--model", f"ollama/{QWEN}")

    assert load_config(config).llm["ocr"].model == f"ollama/{QWEN}"


def test_disable_switches_images_off_and_keeps_the_model(monkeypatch, config):
    with_ocr(config, DEEPSEEK)

    result = sb(config, "disable")

    cfg = load_config(config)
    assert result.exit_code == 0 and not cfg.ocr_on and cfg.llm["ocr"].model == f"ollama/{DEEPSEEK}"
    assert "off" in result.stdout and "sb ocr enable" in result.stdout


def test_disable_when_it_was_never_on_says_so_and_writes_nothing(config):
    before = config.read_text()

    result = sb(config, "disable")

    assert result.exit_code == 0 and "already off" in result.stdout
    assert config.read_text() == before


# --- sb init -----------------------------------------------------------------------------------


def init(tmp_path, *extra, input=None):
    cfg = tmp_path / "cfg" / "config.toml"
    args = ["init", "--vault", str(tmp_path / "Brain"), "--config-file", str(cfg), *extra]
    return CliRunner().invoke(app, args, input=input), cfg


def test_init_with_an_ocr_model_flag_writes_it_and_prints_the_pull_command(tmp_path, monkeypatch):
    server = Ollama(monkeypatch, models=[])

    result, cfg = init(tmp_path, "--no-obsidian", "--ocr", "--ocr-model", DEEPSEEK)

    assert result.exit_code == 0, result.output
    assert load_config(cfg).llm["ocr"].model == f"ollama/{DEEPSEEK}"
    assert server.pulls == [] and f"ollama pull {DEEPSEEK}" in result.stdout


def test_init_downloads_the_ocr_model_only_with_its_flag(tmp_path, monkeypatch):
    server = Ollama(monkeypatch, models=[])

    init(tmp_path, "--no-obsidian", "--ocr", "--ocr-model", QWEN)
    assert server.pulls == []

    result, _ = init(
        tmp_path / "b", "--no-obsidian", "--ocr", "--ocr-model", QWEN, "--pull-ocr-model"
    )
    assert server.pulls == [QWEN] and "success" in result.stdout


def test_the_model_flags_without_ocr_are_an_error_and_nothing_is_written(tmp_path, monkeypatch):
    server = Ollama(monkeypatch)

    for flags in (["--ocr-model", QWEN, "--pull-ocr-model"], ["--no-ocr", "--pull-ocr-model"]):
        result, cfg = init(tmp_path, "--no-obsidian", *flags)
        assert result.exit_code == 1 and "go with --ocr" in result.output and not cfg.exists()
    assert server.pulls == []


def test_init_leaves_images_off_unless_asked(tmp_path, monkeypatch):
    server = Ollama(monkeypatch)

    result, cfg = init(tmp_path, "--no-obsidian")

    assert result.exit_code == 0 and "ocr" not in load_config(cfg).llm and server.pulls == []


def test_init_refuses_an_ocr_model_name_that_is_not_an_ollama_name(tmp_path, monkeypatch):
    Ollama(monkeypatch)

    result, cfg = init(tmp_path, "--no-obsidian", "--ocr", "--ocr-model", 'x"\n[evil]')

    assert result.exit_code == 1 and "model name" in result.output and not cfg.exists()


def test_init_picks_the_small_model_whatever_the_memory_when_no_model_is_named(
    tmp_path, monkeypatch
):
    Ollama(monkeypatch, ram=8.0)
    _, small = init(tmp_path / "a", "--no-obsidian", "--ocr")
    Ollama(monkeypatch, ram=32.0)
    _, big = init(tmp_path / "b", "--no-obsidian", "--ocr")

    assert load_config(small).llm["ocr"].model == f"ollama/{QWEN}"
    assert load_config(big).llm["ocr"].model == f"ollama/{QWEN}"  # DeepSeek only on request


def interactive(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_run_wizard", lambda script, config: None)


# language en, no Obsidian, local model, Ollama, this Mac, no nightly job, no remote
BASICS = ["1", "n", "1", "1", "", "n", ""]


def test_the_interactive_init_asks_about_images_and_no_keeps_everything_off(tmp_path, monkeypatch):
    interactive(monkeypatch)
    server = Ollama(monkeypatch)

    result, cfg = init(
        tmp_path, input="\n".join([*BASICS, "n", "n"]) + "\n"
    )  # ..., images no, Gmail no

    assert result.exit_code == 0, result.output
    assert (
        "Read images and scanned PDFs (jpg, png, ...)? It needs a local vision model."
        in result.stdout
    )
    assert "ocr" not in load_config(cfg).llm and server.pulls == []


def test_the_interactive_init_shows_the_presets_and_recommends_one_for_this_machine(
    tmp_path, monkeypatch
):
    interactive(monkeypatch)
    Ollama(monkeypatch, models=[QWEN], ram=8.0)

    # images yes; the recommended model (Enter); it is installed, so no download question; Gmail no
    result, cfg = init(tmp_path, input="\n".join([*BASICS, "y", "", "n"]) + "\n")

    out = result.stdout
    assert result.exit_code == 0, out
    assert DEEPSEEK in out and "6.7 GB" in out and QWEN in out and "1.9 GB" in out
    assert "recommended for this machine" in out and "8 GB" in out
    assert load_config(cfg).llm["ocr"].model == f"ollama/{QWEN}"
    assert "already installed" in out and "Download it now?" not in out


def test_the_interactive_init_lets_you_type_another_model_and_asks_before_downloading(
    tmp_path, monkeypatch
):
    interactive(monkeypatch)
    server = Ollama(monkeypatch, models=[])
    # images yes; option 3 (another model), its name; "Download it now?" no; Gmail no
    answers = [*BASICS, "y", "3", "llava:7b", "n", "n"]

    result, cfg = init(tmp_path, input="\n".join(answers) + "\n")

    assert result.exit_code == 0, result.output
    assert load_config(cfg).llm["ocr"].model == "ollama/llava:7b"
    assert "Download it now?" in result.stdout and server.pulls == []
    assert "ollama pull llava:7b" in result.stdout  # said no: here is the command for later


def test_the_interactive_init_downloads_after_a_yes(tmp_path, monkeypatch):
    interactive(monkeypatch)
    server = Ollama(monkeypatch, models=[], ram=8.0)

    result, _ = init(tmp_path, input="\n".join([*BASICS, "y", "", "y", "n"]) + "\n")

    assert server.pulls == [QWEN] and result.exit_code == 0, result.output


def test_init_does_not_touch_the_ocr_settings_of_a_config_that_already_exists(
    tmp_path, monkeypatch
):
    server = Ollama(monkeypatch)
    _, cfg = init(tmp_path, "--no-obsidian")
    before = cfg.read_text()

    result, _ = init(tmp_path, "--no-obsidian", "--ocr", "--pull-ocr-model")

    assert cfg.read_text() == before and server.pulls == []
    assert "sb ocr enable" in result.stdout  # the way to do it on a config that exists
