"""`sb update` and `sb version --check`. No test runs brew, uv, pipx or pip, or reaches the network:
the release and the command runner are fakes."""

import pytest
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli import update as updater
from esbi_cli.cli import app

V2 = updater.Release("0.2.0", "https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.2.0")


class FakeRunner:
    """Stands in for update.run_command: records the argument lists, returns a fixed exit code."""

    def __init__(self, code=0):
        self.code, self.calls = code, []

    def __call__(self, argv):
        self.calls.append(argv)
        if isinstance(self.code, Exception):
            raise self.code
        return self.code


@pytest.fixture
def world(monkeypatch):
    """Installed 0.1.0, installed with Homebrew, GitHub says 0.2.0, nobody at the keyboard."""
    state = {"release": V2, "asked": 0}
    runner = FakeRunner()

    def latest():
        state["asked"] += 1
        return state["release"]

    monkeypatch.setattr(cli, "__version__", "0.1.0")
    monkeypatch.setattr(updater, "latest_release", latest)
    monkeypatch.setattr(updater, "install_method", lambda prefix, package_dir: "brew")
    monkeypatch.setattr(updater, "run_command", runner)
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    state["runner"] = runner
    return state


def sb(*args, input=None):
    return CliRunner().invoke(app, list(args), input=input)


def test_plain_version_is_offline_and_prints_only_the_version(world):
    result = sb("version")

    assert result.stdout.strip() == "0.1.0" and world["asked"] == 0


def test_version_check_asks_afresh_and_says_how_to_update(world):
    result = sb("version", "--check")

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout and "0.2.0" in result.stdout
    assert "sb update" in result.stdout and world["asked"] == 1


def test_version_check_says_when_you_are_up_to_date(world):
    world["release"] = updater.Release("0.1.0", V2.url)

    result = sb("version", "--check")

    assert "up to date" in result.stdout and "sb update" not in result.stdout


def test_version_check_says_so_when_it_cannot_reach_github(world):
    world["release"] = None

    result = sb("version", "--check")

    assert result.exit_code == 0 and "could not check" in result.stdout.lower()


def test_update_without_a_terminal_and_without_yes_refuses_and_runs_nothing(world):
    result = sb("update")

    assert result.exit_code == 1 and "--yes" in result.output
    assert world["runner"].calls == []


def test_update_dry_run_prints_the_command_and_runs_nothing(world):
    result = sb("update", "--dry-run")

    assert result.exit_code == 0
    assert "brew upgrade rubenamaury/esbi-cli/esbi-cli" in result.stdout
    assert "installed: 0.1.0" in result.stdout and "latest:    0.2.0" in result.stdout
    assert "brew" in result.stdout.split("method:")[1].split("\n")[0]
    assert world["runner"].calls == []


def test_update_yes_runs_the_exact_argument_list_and_reports_success(world):
    result = sb("update", "--yes")

    assert result.exit_code == 0
    assert world["runner"].calls == [["brew", "upgrade", "rubenamaury/esbi-cli/esbi-cli"]]
    assert "Updated. Run `sb version` to confirm" in result.stdout


def test_update_asks_at_a_terminal_and_only_a_yes_runs_it(world, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)

    no = sb("update", input="n\n")
    assert no.exit_code == 0 and "Run it now? [y/N]" in no.stdout
    assert world["runner"].calls == []
    assert sb("update", input="\n").exit_code == 0 and world["runner"].calls == []  # default: no

    assert sb("update", input="y\n").exit_code == 0
    assert len(world["runner"].calls) == 1


def test_a_failing_update_command_is_reported_with_its_exit_code(world):
    world["runner"].code = 3

    result = sb("update", "--yes")

    assert result.exit_code == 3
    assert "exited with code 3" in result.output and "Updated" not in result.output


def test_a_missing_tool_is_said_plainly(world):
    world["runner"].code = FileNotFoundError("brew")

    result = sb("update", "-y")

    assert result.exit_code == 1 and "`brew` was not found" in result.output


def test_already_current_says_so_and_runs_nothing(world):
    world["release"] = updater.Release("0.1.0", V2.url)

    result = sb("update", "--yes")

    assert result.exit_code == 0 and "up to date" in result.stdout.lower()
    assert world["runner"].calls == []


def test_update_always_asks_afresh_ignoring_the_daily_cache(world):
    sb("update", "--dry-run")
    sb("update", "--dry-run")

    assert world["asked"] == 2


def test_update_that_cannot_reach_github_fails_without_running_anything(world):
    world["release"] = None

    result = sb("update", "--yes")

    assert result.exit_code == 1 and "could not check" in result.output.lower()
    assert world["runner"].calls == []


def test_an_install_with_no_command_gets_the_message_and_nothing_runs(world, monkeypatch):
    monkeypatch.setattr(updater, "install_method", lambda prefix, package_dir: "editable")

    result = sb("update", "--yes")

    assert result.exit_code == 0 and "git pull" in result.stdout
    assert world["runner"].calls == []


def test_a_pinned_uv_tool_is_told_to_reinstall_not_upgraded(world, monkeypatch):
    monkeypatch.setattr(updater, "install_method", lambda prefix, package_dir: "uv-tool")
    monkeypatch.setattr(updater, "pinned_source", lambda prefix: ("git", "https://x.test/r"))

    result = sb("update", "--yes")

    assert "cannot move" in result.stdout and "uv tool install --force" in result.stdout
    assert world["runner"].calls == []


def test_the_runner_never_uses_a_shell_or_changes_the_environment(monkeypatch):
    seen = {}

    def fake_run(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    assert updater.run_command(["brew", "upgrade", "x"]) == 0
    assert seen["args"] == (["brew", "upgrade", "x"],)
    assert not seen["kwargs"].get("shell") and "env" not in seen["kwargs"]
    assert "capture_output" not in seen["kwargs"]  # the output streams to the terminal
