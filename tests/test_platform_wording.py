"""What `sb` says about "this Mac", the Keychain and launchd is true on the system it runs on:
macOS-only things are named as macOS-only on Linux, never assumed."""

import sys

import pytest
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli.cli import app
from esbi_cli.mail import credentials
from esbi_cli.mail.credentials import CredentialError, get_password, save_password


def _init(tmp_path, *extra, input=None):
    config = tmp_path / "cfg" / "config.toml"
    args = ["init", "--vault", str(tmp_path / "Brain"), "--config-file", str(config), *extra]
    return CliRunner().invoke(app, args, input=input), config


def test_init_says_this_mac_only_on_a_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    linux, _ = _init(tmp_path / "l", "--model", "local")
    monkeypatch.setattr(sys, "platform", "darwin")
    mac, _ = _init(tmp_path / "m", "--model", "local")

    assert "Everything stays on this machine" in linux.stdout and "Mac" not in linux.stdout
    assert "Everything stays on this Mac" in mac.stdout


def test_the_interactive_questions_say_this_machine_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_run_wizard", lambda script, config: None)
    answers = "\n".join(["1", "n", "1", "1", "", "n", "", "n", "n"]) + "\n"

    result, _ = _init(tmp_path, input=answers)

    assert result.exit_code == 0, result.output
    assert "On this machine with a local model" in result.stdout
    assert "runs on this machine" in result.stdout
    assert "Mac" not in result.stdout


def test_the_email_block_names_the_keyring_of_the_system(tmp_path, monkeypatch):
    from esbi_cli.init import set_email_block

    path = tmp_path / "config.toml"
    for platform, word, other in (
        ("linux", "system keyring", "Keychain"),
        ("darwin", "Keychain", "keyring"),
    ):
        monkeypatch.setattr(sys, "platform", platform)
        path.write_text("[paths]\nvault = 'x'\n")
        set_email_block(path, "me@example.test")
        assert word in path.read_text() and other not in path.read_text()


class _Failing:
    def __init__(self, error):
        self.error = error

    def get_password(self, *args):
        raise self.error

    def set_password(self, *args):
        raise self.error


def test_credential_errors_say_keychain_on_a_mac_and_keyring_elsewhere(monkeypatch):
    from keyring.errors import KeyringLocked

    backend = _Failing(KeyringLocked("locked"))
    for platform, word, other in (
        ("darwin", "Keychain", "keyring"),
        ("linux", "keyring", "Keychain"),
    ):
        monkeypatch.setattr(sys, "platform", platform)
        for action in (
            lambda: get_password("me@x.test", backend=backend),
            lambda: save_password("me@x.test", "pw", backend=backend),
        ):
            with pytest.raises(CredentialError) as raised:
                action()
            assert word in str(raised.value) and other not in str(raised.value)


def test_a_missing_password_names_the_store_of_the_system(monkeypatch):
    class Empty:
        def get_password(self, *args):
            return None

    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(CredentialError) as raised:
        get_password("me@x.test", backend=Empty())

    assert "Keychain" not in str(raised.value) and "keyring" in str(raised.value)


def test_a_blocked_read_does_not_talk_about_a_mac_dialog_on_linux(monkeypatch):
    import threading

    class Blocks:
        def get_password(self, *args):
            threading.Event().wait(5)

    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(CredentialError) as raised:
        get_password("me@x.test", backend=Blocks(), timeout_seconds=0.05)

    assert "Mac" not in str(raised.value) and "Keychain" not in str(raised.value)


def test_set_password_and_doctor_name_the_store_of_the_system(
    tmp_path, vault, config_file, monkeypatch
):
    from test_doctor import doc, healthy

    monkeypatch.setattr(sys, "platform", "linux")
    healthy(monkeypatch, vault)

    saved = CliRunner().invoke(
        app, ["email", "set-password", "--stdin", "--config", str(config_file)], input="pw\n"
    )
    checked = doc(config_file)

    assert "Saved to the system keyring." in saved.stdout
    assert "in the system keyring" in checked.stdout and "Keychain" not in checked.stdout


def test_doctor_says_the_nightly_job_is_macos_only_where_there_is_no_launchd(
    vault, config_file, monkeypatch
):
    from test_doctor import doc, healthy

    healthy(monkeypatch, vault)
    monkeypatch.setattr(sys, "platform", "linux")

    def no_launchctl(*args, **kwargs):
        raise FileNotFoundError("launchctl")

    monkeypatch.setattr(credentials.keyring, "get_password", credentials.keyring.get_password)
    from esbi_cli import schedule as launchd

    monkeypatch.setattr(launchd, "run_launchctl", no_launchctl)

    result = doc(config_file)

    assert "launchd, which only macOS has" in result.stdout and "cron" in result.stdout


def test_the_help_texts_do_not_assume_a_mac():
    for command in (["init", "--help"], ["ocr", "enable", "--help"]):
        result = CliRunner().invoke(app, command)
        assert "this Mac" not in result.stdout, command


def test_the_ocr_preset_notes_do_not_assume_a_mac_either():
    from esbi_cli import ocr_models

    assert "fits an 8 GB Mac" not in ocr_models.QWEN.note
