from datetime import datetime

import httpx
import pytest
from conftest import FakeLaunchctl
from typer.testing import CliRunner

from esbi_cli import config as config_module
from esbi_cli import doctor
from esbi_cli import schedule as launchd
from esbi_cli.cli import app
from esbi_cli.mail import credentials
from esbi_cli.queue import Queue
from esbi_cli.runlog import RunLog, RunRecord


def fake_tags(*models):
    def get(url, **kwargs):
        if models == ("DOWN",):
            raise httpx.ConnectError("connection refused")
        return httpx.Response(
            200, json={"models": [{"name": m} for m in models]}, request=httpx.Request("GET", url)
        )

    return get


def healthy(monkeypatch, vault, *, models=("fake:latest",), job_loaded=True):
    monkeypatch.setattr(doctor.httpx, "get", fake_tags(*models))
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(loaded=job_loaded))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/sb")
    credentials.save_password("me@example.test", "pw")
    (vault.root / ".obsidian").mkdir(exist_ok=True)
    now = datetime.now()
    RunLog(vault.root / ".esbi" / "runs.jsonl").record(
        RunRecord(now, now, 3, 0, 0, 1200, None, "scheduled")
    )


def doc(config_file, *extra):
    return CliRunner().invoke(app, ["doctor", "--config", str(config_file), *extra])


def test_a_healthy_setup_reports_ok_everywhere_and_exits_zero(vault, config_file, monkeypatch):
    healthy(monkeypatch, vault)

    result = doc(config_file)

    assert result.exit_code == 0, result.output
    assert "FAIL" not in result.stdout and "WARN" not in result.stdout
    for name in (
        "config",
        "vault",
        "notes language",
        "obsidian",
        "queue",
        "model summarize",
        "email",
        "nightly job",
    ):
        assert f"ok   {name}" in result.stdout, name
    assert "ok   last run" in result.stdout and "ok   global install" in result.stdout


@pytest.mark.parametrize(
    ("setup", "hint"),
    [
        ({"models": ("DOWN",)}, "brew services start ollama"),  # Ollama not running
        ({"models": ("llama3.2:latest",)}, "ollama pull fake"),  # model not installed
    ],
)
def test_a_model_that_cannot_be_used_is_a_problem_with_the_fix(
    vault, config_file, monkeypatch, setup, hint
):
    healthy(monkeypatch, vault, **setup)

    result = doc(config_file)

    assert result.exit_code == 1
    assert "FAIL model summarize" in result.stdout and hint in result.stdout


def test_a_cloud_model_needs_its_api_key_in_the_environment(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cloud = tmp_path / "cloud.toml"
    cloud.write_text(config_file.read_text().replace("ollama/fake", "openai/gpt-x"))

    result = doc(cloud)

    assert result.exit_code == 1
    assert "FAIL model summarize" in result.stdout and "OPENAI_API_KEY" in result.stdout


def test_email_needs_its_password_in_the_keychain_only_when_enabled(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    monkeypatch.setattr(
        credentials, "keyring", type("Empty", (), {"get_password": lambda *a: None})()
    )

    missing = doc(config_file)
    assert missing.exit_code == 1
    assert "FAIL email" in missing.stdout and "sb email set-password" in missing.stdout

    off = tmp_path / "off.toml"
    off.write_text(config_file.read_text().replace("enabled = true", "enabled = false"))
    assert "ok   email: off" in doc(off).stdout


def test_things_that_are_only_inconvenient_are_warnings_and_do_not_fail(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(doctor.httpx, "get", fake_tags("fake:latest"))
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(loaded=False))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    credentials.save_password("me@example.test", "pw")
    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    queue.add("https://x.test/bad", origin="inbox")
    for _ in range(3):
        queue.fail(queue.claim(1)[0].id, "boom")

    result = doc(config_file)

    assert result.exit_code == 0, result.output
    for name, fix in [
        ("obsidian", "Open folder as vault"),
        ("queue", "sb retry"),
        ("nightly job", "sb schedule install"),
        ("last run", "no scheduled run yet"),
        ("global install", "uv tool install --editable"),
    ]:
        assert f"WARN {name}" in result.stdout and fix in result.stdout, name


def test_a_broken_vault_or_a_missing_config_is_reported_without_a_traceback(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    (vault.root / "SCHEMA.md").unlink()
    broken = doc(config_file)
    assert broken.exit_code == 1 and "FAIL vault" in broken.stdout and "SCHEMA.md" in broken.stdout

    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATHS", ())
    monkeypatch.delenv("ESBI_CONFIG", raising=False)
    nothing = CliRunner().invoke(app, ["doctor", "--config", str(tmp_path / "nope.toml")])
    assert nothing.exit_code == 1
    assert "FAIL config" in nothing.stdout and "Traceback" not in nothing.output


def test_a_configured_synthesis_model_is_checked_like_the_others(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)  # only fake:latest is installed
    strong = tmp_path / "strong.toml"
    strong.write_text(config_file.read_text() + '\n[llm.synthesize]\nmodel = "ollama/strong"\n')

    result = doc(strong)

    assert result.exit_code == 1
    assert "ok   model summarize" in result.stdout
    assert "FAIL model synthesize" in result.stdout and "ollama pull strong" in result.stdout


def test_a_configured_embedding_model_is_checked_and_a_remote_one_is_not_an_email_warning(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    cfg = tmp_path / "embed.toml"
    cfg.write_text(config_file.read_text() + '\n[llm.embed]\nmodel = "ollama/nomic-embed-text"\n')

    missing = doc(cfg)

    assert "FAIL model embed" in missing.stdout and "ollama pull nomic-embed-text" in missing.stdout

    remote = tmp_path / "remote.toml"
    remote.write_text(
        config_file.read_text()
        + '\n[llm.embed]\nmodel = "ollama/fake"\nbase_url = "http://gpu.test:11434"\n'
    )
    assert "WARN email privacy" not in doc(remote).stdout  # the embedder never gets email text


@pytest.mark.parametrize(
    "which, status, expected",
    [
        ("/usr/local/bin/claude", {"loggedIn": True, "email": "me@x.test"}, "me@x.test"),
        ("/usr/local/bin/claude", {"loggedIn": False}, "claude auth login"),
        (None, None, "not installed"),
    ],
)
def test_a_subscription_model_needs_the_claude_tool_installed_and_logged_in(
    tmp_path, vault, config_file, monkeypatch, which, status, expected
):
    import json
    import subprocess

    healthy(monkeypatch, vault)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: which if name == "claude" else None)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps(status), ""),
    )
    sub = tmp_path / "sub.toml"
    sub.write_text(config_file.read_text().replace("ollama/fake", "claude-cli/default"))

    result = doc(sub)

    assert expected in result.stdout
    assert ("FAIL model summarize" in result.stdout) == (expected != "me@x.test")


def test_a_configured_fallback_model_is_checked_too(tmp_path, vault, config_file, monkeypatch):
    healthy(monkeypatch, vault, models=("fake:latest",))
    cfg = tmp_path / "fb.toml"
    cfg.write_text(
        config_file.read_text().replace(
            'model = "ollama/fake"', 'model = "ollama/fake"\nfallback = "ollama/missing"'
        )
    )

    result = doc(cfg)

    assert (
        "FAIL model summarize fallback" in result.stdout and "ollama pull missing" in result.stdout
    )


def test_a_cloud_model_without_a_private_model_warns_that_email_will_be_refused(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cloud = tmp_path / "cloud.toml"
    cloud.write_text(config_file.read_text().replace("ollama/fake", "openai/gpt-x"))

    result = doc(cloud)

    assert "WARN email privacy" in result.stdout and "[llm.private]" in result.stdout

    local = tmp_path / "with-private.toml"
    local.write_text(cloud.read_text() + '\n[llm.private]\nmodel = "ollama/fake"\n')
    ok = doc(local)
    assert "WARN email privacy" not in ok.stdout and "ok   model private" in ok.stdout


def test_a_job_installed_for_another_time_than_the_config_says_is_a_warning_with_the_fix(
    tmp_path, vault, config_file, monkeypatch
):
    from esbi_cli.schedule import LABEL, render_plist

    healthy(monkeypatch, vault)
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / f"{LABEL}.plist").write_bytes(
        render_plist(config=config_file, log_dir=tmp_path, venv=tmp_path, at=(3, 0))
    )
    monkeypatch.setattr(doctor, "AGENTS_DIR", agents)
    changed = tmp_path / "changed.toml"
    changed.write_text(config_file.read_text().replace("[run]", '[run]\nnightly_time = "05:15"'))

    result = doc(changed)

    assert "WARN nightly job" in result.stdout and "05:15" in result.stdout
    assert "sb schedule install" in result.stdout


def test_a_job_that_points_into_a_versioned_homebrew_folder_is_a_warning_with_the_fix(
    tmp_path, vault, config_file, monkeypatch
):
    from esbi_cli.schedule import LABEL

    healthy(monkeypatch, vault)
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    old = render_plist_for(config_file, tmp_path, "/opt/homebrew/Cellar/esbi-cli/0.1.0/libexec")
    (agents / f"{LABEL}.plist").write_bytes(old)
    monkeypatch.setattr(doctor, "AGENTS_DIR", agents)

    result = doc(config_file)

    assert "WARN nightly job" in result.stdout and "Cellar" in result.stdout
    assert "sb schedule install" in result.stdout


def test_a_job_that_points_at_the_stable_homebrew_path_is_fine(
    tmp_path, vault, config_file, monkeypatch
):
    from esbi_cli.schedule import LABEL

    healthy(monkeypatch, vault)
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    new = render_plist_for(config_file, tmp_path, "/opt/homebrew/opt/esbi-cli/libexec")
    (agents / f"{LABEL}.plist").write_bytes(new)
    monkeypatch.setattr(doctor, "AGENTS_DIR", agents)

    assert "ok   nightly job" in doc(config_file).stdout


def render_plist_for(config_file, tmp_path, venv):
    """A plist as an older esbi-cli would have written it: the venv path is taken literally."""
    import plistlib

    data = plistlib.loads(launchd.render_plist(config=config_file, log_dir=tmp_path, venv=tmp_path))
    data["ProgramArguments"][2] = f"exec {venv}/bin/sb run --if-due --config {config_file}"
    return plistlib.dumps(data)


def test_without_obsidian_the_vault_is_not_expected_to_be_opened_in_it(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    plain = tmp_path / "plain.toml"
    plain.write_text(
        config_file.read_text().replace('language = "es"', 'language = "es"\nviewer = "none"')
    )

    result = doc(plain)

    assert "WARN obsidian" not in result.stdout and "ok   obsidian: not used" in result.stdout


@pytest.mark.parametrize(
    "server, expected",
    [
        ({"data": [{"id": "qwen2.5-7b-instruct"}]}, "ok   model summarize"),
        ({"data": [{"id": "otro-modelo"}]}, "FAIL model summarize"),
        (None, "LM Studio is not reachable"),
    ],
)
def test_an_lm_studio_model_must_be_served_by_the_local_server(
    tmp_path, vault, config_file, monkeypatch, server, expected
):
    healthy(monkeypatch, vault)

    def get(url, **kwargs):
        if server is None:
            raise httpx.ConnectError("connection refused")
        assert url == "http://localhost:1234/v1/models"
        return httpx.Response(200, json=server, request=httpx.Request("GET", url))

    monkeypatch.setattr(doctor.httpx, "get", get)
    cfg = tmp_path / "lm.toml"
    cfg.write_text(config_file.read_text().replace("ollama/fake", "lmstudio/qwen2.5-7b-instruct"))

    result = doc(cfg)

    assert expected in result.stdout


def test_a_cloud_model_as_the_private_model_is_a_failure_and_a_cloud_fallback_counts_too(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    bad = tmp_path / "bad.toml"
    bad.write_text(config_file.read_text() + '\n[llm.private]\nmodel = "openai/gpt-x"\n')

    result = doc(bad)

    assert (
        result.exit_code == 1
        and "FAIL email privacy" in result.stdout
        and "[llm.private]" in result.stdout
    )

    leaky = tmp_path / "leaky.toml"
    leaky.write_text(
        config_file.read_text()
        + '\n[llm.private]\nmodel = "ollama/fake"\nfallback = "openai/gpt-x"\n'
    )
    assert "FAIL email privacy" in doc(leaky).stdout


def test_doctor_says_ocr_is_off_and_how_to_turn_it_on_without_calling_it_a_problem(
    vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)

    result = doc(config_file)

    assert result.exit_code == 0 and "ok   ocr: off (optional)" in result.stdout
    assert "[llm.ocr]" in result.stdout


def test_doctor_checks_that_the_ocr_model_is_installed(tmp_path, vault, config_file, monkeypatch):
    ocr = tmp_path / "ocr.toml"
    ocr.write_text(config_file.read_text() + '\n[llm.ocr]\nmodel = "ollama/qwen3-vl:2b-instruct"\n')
    healthy(monkeypatch, vault)

    missing = doc(ocr)

    assert missing.exit_code == 1 and "FAIL model ocr" in missing.stdout
    assert "ollama pull qwen3-vl:2b-instruct" in missing.stdout

    healthy(monkeypatch, vault, models=("fake:latest", "qwen3-vl:2b-instruct"))
    assert "ok   model ocr" in doc(ocr).stdout


def test_doctor_fails_an_ocr_model_that_would_send_images_away(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    bad = tmp_path / "bad.toml"
    bad.write_text(config_file.read_text() + '\n[llm.ocr]\nmodel = "openai/gpt-x"\n')

    result = doc(bad)

    assert result.exit_code == 1 and "FAIL ocr" in result.stdout and "[llm.ocr]" in result.stdout


def test_a_local_runtime_on_another_machine_warns_that_the_notes_text_goes_there(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    remote = tmp_path / "remote.toml"
    remote.write_text(
        config_file.read_text().replace(
            'model = "ollama/fake"',
            'model = "ollama/fake"\nbase_url = "http://gpu-box.lan:11434"\n'
            'fallback = "lmstudio/other"',
        )
        + '\n[llm.ask]\nmodel = "ollama/fake"\n'  # this one stays on the Mac
    )

    result = doc(remote)

    assert "WARN server summarize" in result.stdout
    assert "gpu-box.lan" in result.stdout and "email is kept off it" in result.stdout
    assert (
        "WARN server summarize fallback" in result.stdout
    )  # the fallback inherits the same server
    assert "WARN server ask" not in result.stdout

    local = doc(config_file)
    assert "WARN server" not in local.stdout and "gpu-box" not in local.stdout


def test_a_remote_private_model_is_one_failure_not_also_a_remote_warning(
    tmp_path, vault, config_file, monkeypatch
):
    healthy(monkeypatch, vault)
    cfg = tmp_path / "private.toml"
    cfg.write_text(
        config_file.read_text()
        + '\n[llm.private]\nmodel = "ollama/fake"\nbase_url = "http://gpu-box.lan:11434"\n'
    )

    result = doc(cfg)

    assert "FAIL email privacy" in result.stdout
    assert "WARN server private" not in result.stdout  # "email is kept off it" would be untrue


def version_line(result):
    return next(line for line in result.stdout.splitlines() if " version: " in line)


@pytest.fixture
def releases(monkeypatch):
    """GitHub answers with `state["release"]`; the update check is allowed; installed is 0.1.0."""
    from esbi_cli import update

    newer = update.Release("0.2.0", "https://github.com/RubenAmaury/esbi-cli/releases")
    state = {"release": newer, "asked": 0}

    def latest():
        state["asked"] += 1
        return state["release"]

    monkeypatch.delenv("ESBI_NO_UPDATE_CHECK")
    monkeypatch.setattr(update, "latest_release", latest)
    monkeypatch.setattr(doctor, "__version__", "0.1.0")
    return state


def test_doctor_warns_when_a_newer_version_is_known_and_says_how_to_update(
    vault, config_file, monkeypatch, releases
):
    healthy(monkeypatch, vault)

    result = doc(config_file)

    assert result.exit_code == 0
    assert version_line(result).strip() == "WARN version: 0.2.0 is available, run `sb update`"


def test_doctor_says_latest_when_there_is_nothing_newer(vault, config_file, monkeypatch, releases):
    from esbi_cli import update

    healthy(monkeypatch, vault)
    releases["release"] = update.Release("0.1.0", releases["release"].url)

    assert version_line(doc(config_file)).strip() == "ok   version: 0.1.0 (latest)"


def test_a_failed_version_check_is_not_a_problem(vault, config_file, monkeypatch, releases):
    healthy(monkeypatch, vault)
    releases["release"] = None

    assert version_line(doc(config_file)).strip() == "ok   version: 0.1.0"


def test_doctor_uses_the_daily_cache(vault, config_file, monkeypatch, releases):
    healthy(monkeypatch, vault)

    doc(config_file)
    doc(config_file)

    assert releases["asked"] == 1


def test_with_the_check_off_doctor_says_so_and_never_asks(
    tmp_path, vault, config_file, monkeypatch, releases
):
    healthy(monkeypatch, vault)
    off = tmp_path / "off.toml"
    off.write_text(config_file.read_text() + "\n[update]\ncheck = false\n")

    by_config = doc(off)
    monkeypatch.setenv("ESBI_NO_UPDATE_CHECK", "1")
    by_environment = doc(config_file)

    for result in (by_config, by_environment):
        assert version_line(result).strip() == "ok   version: 0.1.0 (update check is off)"
    assert releases["asked"] == 0


def test_doctor_survives_a_version_check_that_blows_up(vault, config_file, monkeypatch, releases):
    from esbi_cli import update

    def broken():
        raise RuntimeError("anything at all")

    healthy(monkeypatch, vault)
    monkeypatch.setattr(update, "latest_release", broken)

    result = doc(config_file)

    assert result.exception is None and "Traceback" not in result.output
    assert version_line(result).strip() == "ok   version: 0.1.0"


def test_where_launchd_does_not_exist_the_job_check_points_at_the_cron_line(
    vault, config_file, monkeypatch
):
    """Linux has no launchctl: the real runner raises FileNotFoundError (an OSError)."""
    healthy(monkeypatch, vault)

    def no_launchctl(args):
        raise FileNotFoundError("launchctl")

    monkeypatch.setattr(launchd, "run_launchctl", no_launchctl)

    result = doc(config_file)

    assert "WARN nightly job: launchd is not available here" in result.stdout
    assert "sb schedule install" in result.stdout.split("nightly job")[1].split("\n")[1]
