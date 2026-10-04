"""git is optional: it gives the vault a history and a backup, and nothing else needs it."""

import shutil

from conftest import FakeLLM, make_plan
from typer.testing import CliRunner

from esbi_cli import cli, doctor, gitops
from esbi_cli import init as init_module
from esbi_cli.cli import app
from esbi_cli.gitops import commit_vault, push_vault


def no_git(monkeypatch):
    monkeypatch.setattr(init_module, "has_git", lambda: False)
    monkeypatch.setattr(doctor, "has_git", lambda: False)


def test_a_vault_is_created_without_a_repository_when_git_is_not_installed(tmp_path, monkeypatch):
    no_git(monkeypatch)

    made = init_module.init_vault(tmp_path / "v")

    assert "git repository" not in made and not (tmp_path / "v" / ".git").exists()
    assert (tmp_path / "v" / "wiki" / "sources").is_dir()


def test_without_a_repository_nothing_is_committed_and_nothing_fails(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Nota.md").write_text("texto")

    assert commit_vault(tmp_path, "mensaje") is False
    assert push_vault(tmp_path) is None


def test_a_missing_git_program_is_a_git_error_not_a_crash(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Nota.md").write_text("texto")
    monkeypatch.setattr(gitops.subprocess, "run", _raise(FileNotFoundError("git")))

    try:
        commit_vault(tmp_path, "mensaje")
    except gitops.GitError as exc:
        assert "git" in str(exc)
    else:
        raise AssertionError("expected GitError")


def _raise(exc):
    def run(*args, **kwargs):
        raise exc

    return run


def test_init_explains_what_is_lost_without_git_and_skips_the_backup_remote(tmp_path, monkeypatch):
    no_git(monkeypatch)
    args = ["init", "--vault", str(tmp_path / "V"), "--config-file", str(tmp_path / "c.toml")]

    result = CliRunner().invoke(app, [*args, "--model", "local", "--remote", "git@x.test:a/b.git"])

    assert result.exit_code == 0, result.output
    assert "git is not installed" in result.stdout and "optional" in result.stdout
    assert "backup remote" in result.stdout.lower() and "skipped" in result.stdout.lower()


def test_doctor_calls_a_vault_without_git_fine_when_git_is_not_installed(vault, monkeypatch):
    no_git(monkeypatch)
    shutil.rmtree(vault.root / ".git")

    checks = {c.name: c for c in doctor._vault(vault.root)}

    assert checks["vault history"].level == "ok" and "optional" in checks["vault history"].text


def test_reingest_refuses_without_history_because_it_could_not_be_undone(
    vault, config_file, monkeypatch
):
    shutil.rmtree(vault.root / ".git")
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))

    result = CliRunner().invoke(app, ["reingest", "--config", str(config_file)])

    assert result.exit_code == 1 and "git" in result.output and "undo" in result.output
