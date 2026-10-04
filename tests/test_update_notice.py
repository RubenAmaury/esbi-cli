"""The one-line notice after a command: when it appears, and above all when it must not (the nightly
run, scripts, failures, the opt-out) and that it never asks the network there."""

import pytest
from conftest import FakeLaunchctl, FakeLLM
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli import schedule as launchd
from esbi_cli import update as updater
from esbi_cli.cli import app

V2 = updater.Release("0.2.0", "https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.2.0")
NOTICE = "esbi-cli 0.2.0 is available (you have 0.1.0). Update with: sb update"


@pytest.fixture
def world(monkeypatch, tmp_path, config_file):
    """A terminal on stderr, installed 0.1.0, GitHub says 0.2.0, the automatic check allowed."""
    state = {"release": V2, "asked": 0}

    def latest():
        state["asked"] += 1
        return state["release"]

    monkeypatch.delenv("ESBI_NO_UPDATE_CHECK")
    monkeypatch.setenv("ESBI_CONFIG", str(config_file))
    monkeypatch.setattr(cli, "__version__", "0.1.0")
    monkeypatch.setattr(cli, "_stderr_is_tty", lambda: True)
    monkeypatch.setattr(updater, "latest_release", latest)
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl())
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    state["config"] = config_file
    return state


def sb(*args, env=None):
    return CliRunner().invoke(app, list(args), env=env)


def test_a_command_run_in_a_terminal_ends_with_one_line_on_stderr(world):
    result = sb("info")

    assert result.exit_code == 0
    assert result.stderr.strip() == NOTICE
    assert NOTICE not in result.stdout  # stdout stays clean for pipes


def test_the_notice_comes_from_the_cache_so_the_network_is_asked_once_a_day(world):
    sb("info")
    sb("info")
    sb("info")

    assert world["asked"] == 1


def test_no_notice_when_you_are_up_to_date_or_the_check_failed(world):
    world["release"] = updater.Release("0.1.0", V2.url)
    assert sb("info").stderr == ""
    world["release"] = None
    assert sb("info", "--config", str(world["config"])).stderr == ""


def test_never_for_a_script_even_when_a_newer_version_is_known(world, monkeypatch):
    monkeypatch.setattr(cli, "_stderr_is_tty", lambda: False)

    result = sb("info")

    assert result.stderr == "" and world["asked"] == 0  # not even a network call


@pytest.mark.parametrize(
    "args",
    [
        ["version"],
        ["update", "--dry-run"],
        ["schedule", "status"],
        ["setup", "--help"],
        ["info", "--help"],
    ],
)
def test_never_after_the_commands_that_manage_the_installation(world, args):
    result = sb(*args)

    assert NOTICE not in result.stderr and NOTICE not in result.stdout
    if args[0] != "update":
        assert world["asked"] == 0


def test_never_after_init(world, tmp_path):
    result = sb(
        "init", "--vault", str(tmp_path / "Brain"), "--config-file", str(tmp_path / "c.toml")
    )

    assert result.exit_code == 0, result.output
    assert NOTICE not in result.stderr and world["asked"] == 0


@pytest.fixture
def plain_config(tmp_path):
    """A config with no mailbox: `sb run` then touches nothing outside the temp vault."""
    from esbi_cli.init import init_vault

    init_vault(tmp_path / "plain-vault")
    path = tmp_path / "plain.toml"
    path.write_text(
        f'[paths]\nvault = "{tmp_path / "plain-vault"}"\n[llm.summarize]\nmodel = "ollama/x"\n'
    )
    return path


def test_never_after_the_nightly_run(world, plain_config):
    result = sb("run", "--if-due", "--config", str(plain_config))

    assert result.exit_code == 0, result.output
    assert NOTICE not in result.stderr and world["asked"] == 0


def test_never_after_a_run_even_in_a_terminal(world, plain_config):
    result = sb("run", "--config", str(plain_config))

    assert result.exit_code == 0, result.output
    assert NOTICE not in result.stderr and world["asked"] == 0


def test_never_after_a_command_that_failed(world):
    result = sb("status", "--config", "/no/such/config.toml")

    assert result.exit_code == 1
    assert NOTICE not in result.stderr and world["asked"] == 0


def test_never_during_shell_completion(world):
    result = sb("--show-completion", env={"_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"})
    complete = sb(env={"_SB_COMPLETE": "complete_bash", "COMP_WORDS": "sb ", "COMP_CWORD": "1"})

    assert NOTICE not in result.stderr and NOTICE not in complete.stderr
    assert world["asked"] == 0


def test_the_environment_variable_switches_it_all_off_without_a_network_call(world):
    result = sb("info", env={"ESBI_NO_UPDATE_CHECK": "1"})

    assert result.stderr == "" and world["asked"] == 0


def test_the_config_switches_it_all_off_without_a_network_call(world, tmp_path):
    off = tmp_path / "off.toml"
    off.write_text(world["config"].read_text() + "\n[update]\ncheck = false\n")

    result = sb("info", env={"ESBI_CONFIG": str(off)})

    assert result.stderr == "" and world["asked"] == 0


def test_a_check_that_blows_up_never_turns_a_successful_command_into_a_traceback(
    world, monkeypatch
):
    """The check is a courtesy: whatever goes wrong inside it, the command's own result stands."""

    def broken():
        raise RuntimeError("anything at all")

    monkeypatch.setattr(updater, "latest_release", broken)

    result = sb("info")

    assert result.exit_code == 0 and result.exception is None
    assert "Traceback" not in result.output


def _config_with(world, tmp_path, name, extra):
    path = tmp_path / name
    path.write_text(world["config"].read_text() + extra)
    return path


def test_the_notice_follows_the_config_the_command_was_given_not_the_default_one(world, tmp_path):
    off = _config_with(world, tmp_path, "off.toml", "\n[update]\ncheck = false\n")

    result = sb("status", "--config", str(off))  # ESBI_CONFIG (check on) is not the one in use

    assert result.exit_code == 0, result.output
    assert result.stderr == "" and world["asked"] == 0


def test_an_explicit_config_that_allows_the_check_wins_over_a_default_that_forbids_it(
    world, tmp_path, monkeypatch
):
    off = _config_with(world, tmp_path, "off.toml", "\n[update]\ncheck = false\n")
    monkeypatch.setenv("ESBI_CONFIG", str(off))

    result = sb("status", "--config", str(world["config"]))

    assert result.stderr.strip() == NOTICE


def test_the_config_of_a_previous_command_does_not_decide_the_next_one(world, tmp_path):
    off = _config_with(world, tmp_path, "off.toml", "\n[update]\ncheck = false\n")
    sb("status", "--config", str(off))

    result = sb("info")  # loads the default config (check on) in its own invocation

    assert result.stderr.strip() == NOTICE


def test_the_environment_variable_still_wins_over_an_explicit_config(world):
    result = sb("status", "--config", str(world["config"]), env={"ESBI_NO_UPDATE_CHECK": "1"})

    assert result.stderr == "" and world["asked"] == 0
