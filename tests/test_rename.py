"""The project was called "second brain" before esbi-cli: an installation made under the old name
keeps working. Each test names the old thing it still understands."""

from datetime import date

from conftest import FakeKeyring, FakeLaunchctl

from esbi_cli import config as config_module
from esbi_cli import export, schedule
from esbi_cli.mail.credentials import get_password
from esbi_cli.report.daily_index import build_daily_index


def test_a_config_named_by_the_old_environment_variable_or_folder_is_still_found(
    tmp_path, monkeypatch
):
    old = tmp_path / "old.toml"
    old.write_text('[paths]\nvault = "/v"\n')
    assert any(p.parts[-2] == "secondbrain" for p in config_module.DEFAULT_CONFIG_PATHS)
    monkeypatch.delenv("ESBI_CONFIG", raising=False)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATHS", ())
    monkeypatch.setenv("SECONDBRAIN_CONFIG", str(old))

    assert config_module.find_config() == old


def test_the_state_folder_of_an_old_vault_is_renamed_and_ignored_by_git(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".secondbrain").mkdir(parents=True)
    (vault / ".secondbrain" / "queue.sqlite3").write_text("queue")
    (vault / ".gitignore").write_text(".DS_Store\n.secondbrain/\n")
    config = tmp_path / "config.toml"
    config.write_text(f'[paths]\nvault = "{vault}"\n')

    config_module.load_config(config)
    config_module.load_config(config)  # a second run changes nothing

    assert (vault / ".esbi" / "queue.sqlite3").read_text() == "queue"
    assert not (vault / ".secondbrain").exists()
    assert ".esbi/*" in (vault / ".gitignore").read_text().splitlines()


def test_the_mail_password_stored_under_the_old_keychain_name_is_found_and_moved():
    keychain = FakeKeyring()
    keychain.store[("secondbrain-imap", "me@x.test")] = "abcdefghijklmnop"

    assert get_password("me@x.test", backend=keychain) == "abcdefghijklmnop"
    assert keychain.store[("esbi-cli-imap", "me@x.test")] == "abcdefghijklmnop"


def test_installing_the_nightly_job_replaces_the_one_loaded_under_the_old_name(tmp_path):
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    old_plist = agents / "com.secondbrain.nightly.plist"
    old_plist.write_text("old")
    launchctl = FakeLaunchctl(loaded=True)

    schedule.install(b"<plist/>", agents, uid=501, launchctl=launchctl)

    assert ["bootout", "gui/501/com.secondbrain.nightly"] in launchctl.calls
    assert not old_plist.exists() and (agents / f"{schedule.LABEL}.plist").exists()


def test_uninstall_also_removes_the_job_of_the_old_name(tmp_path):
    (tmp_path / "com.secondbrain.nightly.plist").write_text("old")

    assert schedule.uninstall(tmp_path, uid=501, launchctl=FakeLaunchctl()) is True
    assert not (tmp_path / "com.secondbrain.nightly.plist").exists()


def test_the_block_of_an_old_home_page_is_updated_and_marked_with_the_new_name(vault, queue):
    home = vault.root / "Home.md"
    home.write_text(
        "# Mi casa\n\nNotas.\n\n<!-- second-brain:start -->\nviejo\n<!-- second-brain:end -->\n"
    )

    build_daily_index(vault, queue, date(2026, 9, 29))
    text = home.read_text()

    assert "second-brain" not in text and "viejo" not in text
    assert text.count("<!-- esbi:start -->") == 1 and "Notas." in text


def test_a_folder_exported_before_the_rename_can_be_replaced(vault, tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / ".second-brain-site").write_text("old")
    (out / "index.html").write_text("old")

    export.export_site(vault, out)

    assert (out / export.MARKER).exists() and not (out / ".second-brain-site").exists()
