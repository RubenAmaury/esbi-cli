import plistlib
from pathlib import Path

import pytest
from conftest import FakeLaunchctl

from esbi_cli.schedule import LABEL, ScheduleError, install, is_loaded, render_plist, uninstall


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
