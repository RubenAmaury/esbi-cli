import plistlib
from pathlib import Path

import pytest
from conftest import FakeLaunchctl

from esbi_cli.schedule import (
    LABEL,
    ScheduleError,
    install,
    is_loaded,
    render_plist,
    stable_prefix,
    uninstall,
)


def test_plist_checks_hourly_and_at_login_using_absolute_paths_and_survives_the_hidden_venv():
    data = render_plist(
        config=Path("/repo/config.toml"),
        log_dir=Path("/vault/.esbi/logs"),
        venv=Path("/envs/esbi-cli"),  # need not live inside the repo
    )

    plist = plistlib.loads(data)

    assert plist["Label"] == LABEL == "com.esbi-cli.nightly"
    assert plist["StartInterval"] == 3600 and plist["RunAtLoad"] is True
    # 03:00 sharp, or at the next wake if the Mac was asleep (launchd catches calendar jobs up)
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
    # not inside ~/Documents: macOS privacy (TCC) blocks background jobs from starting there
    assert plist["WorkingDirectory"] == str(Path.home())
    assert plist["StandardOutPath"] == plist["StandardErrorPath"]
    assert plist["StandardOutPath"] == "/vault/.esbi/logs/nightly.log"
    assert "/usr/bin" in plist["EnvironmentVariables"]["PATH"]  # git lives there

    shell, flag, command = plist["ProgramArguments"]
    assert (shell, flag) == ("/bin/bash", "-c")
    assert "chflags -R nohidden /envs/esbi-cli" in command  # macOS may flag the venv hidden
    assert "/envs/esbi-cli/bin/sb run --if-due --config /repo/config.toml" in command
    assert "exec /usr/bin/caffeinate -i " in command  # the Mac must not idle-sleep mid-run


def test_paths_with_spaces_are_quoted_in_the_command():
    plist = plistlib.loads(
        render_plist(
            config=Path("/my repo/c.toml"),
            log_dir=Path("/l"),
            venv=Path("/my env"),
        )
    )
    assert (
        "'/my env/bin/sb' run --if-due --config '/my repo/c.toml'" in (plist["ProgramArguments"][2])
    )


def test_install_writes_the_plist_and_loads_it_replacing_any_previous_version(tmp_path):
    launchctl = FakeLaunchctl(loaded=True)

    path = install(b"<plist/>", agents_dir=tmp_path / "LaunchAgents", uid=501, launchctl=launchctl)

    assert path == tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    assert path.read_bytes() == b"<plist/>"
    assert launchctl.calls[-2:] == [  # (before them, a job of the old name is unloaded)
        ["bootout", f"gui/501/{LABEL}"],
        ["bootstrap", "gui/501", str(path)],
    ]
    assert is_loaded(uid=501, launchctl=launchctl) is True


def test_install_reports_launchctl_errors(tmp_path):
    with pytest.raises(ScheduleError, match="Bootstrap failed: Input/output error"):
        install(
            b"x",
            agents_dir=tmp_path,
            uid=501,
            launchctl=FakeLaunchctl(fail="Bootstrap failed: Input/output error"),
        )


def test_uninstall_unloads_and_removes_the_plist_and_is_safe_to_repeat(tmp_path):
    launchctl = FakeLaunchctl()
    path = install(b"x", agents_dir=tmp_path, uid=501, launchctl=launchctl)

    assert uninstall(agents_dir=tmp_path, uid=501, launchctl=launchctl) is True
    assert not path.exists() and is_loaded(uid=501, launchctl=launchctl) is False
    assert uninstall(agents_dir=tmp_path, uid=501, launchctl=launchctl) is False


def test_the_calendar_entry_follows_the_chosen_time():
    data = render_plist(
        config=Path("/repo/config.toml"),
        log_dir=Path("/vault/logs"),
        venv=Path("/envs/sb"),
        at=(4, 30),
    )

    assert plistlib.loads(data)["StartCalendarInterval"] == {"Hour": 4, "Minute": 30}


@pytest.mark.parametrize(
    ("cellar", "opt"),
    [
        ("/opt/homebrew/Cellar/esbi-cli/0.1.0/libexec", "/opt/homebrew/opt/esbi-cli/libexec"),
        ("/usr/local/Cellar/esbi-cli/0.1.0/libexec", "/usr/local/opt/esbi-cli/libexec"),
        (
            "/home/linuxbrew/.linuxbrew/Cellar/esbi-cli/0.2.0/libexec",
            "/home/linuxbrew/.linuxbrew/opt/esbi-cli/libexec",
        ),
    ],
)
def test_a_homebrew_prefix_is_replaced_by_the_stable_path_brew_keeps_pointing_at_the_current_version(
    cellar, opt
):
    assert stable_prefix(Path(cellar)) == Path(opt)


@pytest.mark.parametrize(
    "prefix",
    [
        "/h/.local/share/uv/tools/esbi-cli",
        "/h/.local/share/venvs/esbi-cli",
        "/opt/homebrew/opt/esbi-cli/libexec",  # already stable
        "/opt/homebrew/Cellar/other-formula/1.0/libexec",
    ],
)
def test_any_other_prefix_is_left_alone(prefix):
    assert stable_prefix(Path(prefix)) == Path(prefix)


def test_the_plist_does_not_point_into_a_version_folder_that_brew_removes_on_upgrade():
    plist = plistlib.loads(
        render_plist(
            config=Path("/c.toml"),
            log_dir=Path("/l"),
            venv=Path("/opt/homebrew/Cellar/esbi-cli/0.1.0/libexec"),
        )
    )

    command = plist["ProgramArguments"][2]
    assert "/opt/homebrew/opt/esbi-cli/libexec/bin/sb run --if-due" in command
    assert "chflags -R nohidden /opt/homebrew/opt/esbi-cli/libexec" in command
    assert "Cellar" not in command


def test_without_launchctl_on_the_path_the_schedule_commands_show_the_cron_line_not_a_traceback(
    tmp_path, config_file, monkeypatch
):
    """The real runner, not a fake: what a Linux machine does when launchctl is simply not there."""
    from typer.testing import CliRunner

    from esbi_cli.cli import app

    monkeypatch.setenv("PATH", str(tmp_path))  # an empty folder: no launchctl
    runner = CliRunner()
    agents = ["--agents-dir", str(tmp_path / "agents")]
    for args in (
        ["schedule", "install", "--config", str(config_file), *agents],
        ["schedule", "status", *agents],
        ["schedule", "uninstall", *agents],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 1, (args, result.output)
        assert "only macOS has" in result.output and "sb run --if-due" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)
