import json
import os
import plistlib
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import keyring.errors
import pytest
from conftest import (
    FakeEmbedder,
    FakeKeyring,
    FakeLaunchctl,
    FakeLLM,
    FakeMailClient,
    add_source,
    make_plan,
    write_daily,
)
from typer.testing import CliRunner

from esbi_cli import __version__, cli
from esbi_cli import schedule as launchd
from esbi_cli.cli import app
from esbi_cli.llm.adapter import LLMError
from esbi_cli.mail import credentials
from esbi_cli.mail.imap import MailError
from esbi_cli.runlock import RunLock
from esbi_cli.runlog import RunLog, RunRecord


def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_import_legacy_then_status_show_the_queued_backlog(tmp_path, vault, config_file):
    old = tmp_path / "old-notes"
    (old / "Links").mkdir(parents=True)
    (old / "Links" / "01-09-2026.md").write_text("[https://a.test/x]\n[https://b.test/y]\n")
    runner = CliRunner()

    imported = runner.invoke(app, ["import-legacy", "--config", str(config_file)])
    status = runner.invoke(app, ["status", "--config", str(config_file)])

    assert imported.exit_code == 0 and "Queued 2" in imported.stdout
    assert status.exit_code == 0 and "queued: 2" in status.stdout
    assert (vault.root / ".esbi" / "queue.sqlite3").exists()


def test_scan_queues_what_was_dropped_in_the_inbox(vault, config_file):
    (vault.root / "inbox" / "Post.md").write_text("---\nsource: https://x.test/p\n---\n" + "x" * 60)

    result = CliRunner().invoke(app, ["scan", "--config", str(config_file)])

    assert result.exit_code == 0 and "Queued 1" in result.stdout
    assert (vault.root / "raw" / "inbox" / "Post.md").exists()
    assert not (vault.root / "inbox" / "Post.md").exists()


def test_run_ingests_the_inbox_and_commits_each_source_to_the_vault(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    (vault.root / "inbox" / "Post.md").write_text(
        "---\nsource: https://x.test/p\ntitle: Arnés de agentes\n---\n" + "Texto del post. " * 10
    )
    runner = CliRunner()

    run = runner.invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.stdout
    assert "ingested: 1" in run.stdout and "failed: 0" in run.stdout
    assert vault.page_path("sources", "Arnés de agentes").exists()
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True
    ).stdout
    assert "ingest: Arnés de agentes" in log
    assert "done: 1" in runner.invoke(app, ["status", "--config", str(config_file)]).stdout
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "- [ ] [[Arnés de agentes]]" in note.read_text(encoding="utf-8")


def test_run_exits_with_an_error_and_keeps_the_queue_when_the_llm_is_unreachable(
    vault, config_file, monkeypatch
):
    class DownLLM(FakeLLM):
        def complete_json(self, **kwargs):
            raise LLMError("localhost:11434 unreachable")

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: DownLLM())
    (vault.root / "inbox" / "Post.md").write_text("---\nsource: https://x.test/p\n---\n" + "x" * 60)
    runner = CliRunner()

    run = runner.invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 1
    assert "queued: 1" in runner.invoke(app, ["status", "--config", str(config_file)]).stdout
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "1 fuente en cola" in note.read_text(encoding="utf-8")  # the morning index still exists
    assert "1 fuente espera" in note.read_text(encoding="utf-8")  # and says why nothing happened


def test_index_marks_ticked_sources_read_and_writes_todays_note(vault, config_file):
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    add_source(vault, "Artículo A", processed=yesterday)
    write_daily(vault, yesterday, "## Procesado hoy\n- [x] [[Artículo A]] — resumen\n")

    result = CliRunner().invoke(app, ["index", "--config", str(config_file)])

    assert result.exit_code == 0, result.stdout
    assert "Marked 1 source as read" in result.stdout
    assert vault.read_page(vault.page_path("sources", "Artículo A")).meta["status"] == "read"
    assert (vault.wiki / "daily" / f"{today.isoformat()}.md").exists()


def test_index_puts_an_unticked_read_source_back_to_processed(vault, config_file):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    add_source(
        vault, "Artículo A", processed=yesterday, status="read", read=date.today().isoformat()
    )
    write_daily(vault, yesterday, "## Procesado hoy\n- [ ] [[Artículo A]] — resumen\n")

    result = CliRunner().invoke(app, ["index", "--config", str(config_file)])

    assert result.exit_code == 0, result.stdout
    assert "Put 1 source back to unread" in result.stdout
    page = vault.read_page(vault.page_path("sources", "Artículo A"))
    assert (page.meta["status"], page.meta["read"]) == ("processed", None)


def test_run_registers_ticks_even_when_there_is_nothing_to_ingest(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    add_source(vault, "Artículo A", processed=yesterday)
    write_daily(vault, yesterday, "- [x] [[Artículo A]]\n")

    run = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.stdout
    assert vault.read_page(vault.page_path("sources", "Artículo A")).meta["status"] == "read"


def _clip(vault, name="Post.md", url="https://x.test/p"):
    (vault.root / "inbox" / name).write_text(
        f"---\nsource: {url}\ntitle: Arnés de agentes\n---\n" + "Texto del post. " * 10
    )


def _forbid_llm(monkeypatch):
    def boom(_cfg):
        raise AssertionError("the LLM must not be created")

    monkeypatch.setattr(cli, "make_llm", boom)


def test_a_scheduled_run_happens_once_a_day_and_is_recorded(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    runner = CliRunner()
    args = ["run", "--if-due", "--config", str(config_file)]

    first = runner.invoke(app, args)

    assert first.exit_code == 0, first.stdout
    assert "ingested: 1" in first.stdout
    [record] = RunLog(vault.root / ".esbi" / "runs.jsonl").runs()
    assert (record.trigger, record.ingested, record.stopped_by) == ("scheduled", 1, None)
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "procesadas: 1, omitidas: 0, fallidas: 0" in note.read_text(encoding="utf-8")

    _forbid_llm(monkeypatch)
    second = runner.invoke(app, args)
    assert second.exit_code == 0 and "not due" in second.stdout.lower()


def test_a_manual_run_is_recorded_as_manual_and_does_not_satisfy_the_nightly(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    runner = CliRunner()

    assert runner.invoke(app, ["run", "--config", str(config_file)]).exit_code == 0
    [record] = RunLog(vault.root / ".esbi" / "runs.jsonl").runs()
    assert record.trigger == "manual"

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    nightly = runner.invoke(app, ["run", "--if-due", "--config", str(config_file)])
    assert "not due" not in nightly.stdout.lower()


def test_a_run_started_while_another_is_active_skips_without_touching_anything(
    vault, config_file, monkeypatch
):
    _forbid_llm(monkeypatch)
    _clip(vault)

    with RunLock(vault.root / ".esbi" / "run.lock"):
        result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 0 and "another run is in progress" in result.stdout.lower()
    assert (vault.root / "inbox" / "Post.md").exists()  # not even scanned
    assert RunLog(vault.root / ".esbi" / "runs.jsonl").runs() == []


def test_schedule_install_writes_a_launch_agent_for_this_project_and_uninstall_removes_it(
    tmp_path, vault, config_file, monkeypatch
):
    launchctl = FakeLaunchctl()
    monkeypatch.setattr(launchd, "run_launchctl", launchctl)
    agents = tmp_path / "LaunchAgents"
    runner = CliRunner()
    where = ["--agents-dir", str(agents)]

    installed = runner.invoke(app, ["schedule", "install", "--config", str(config_file), *where])

    assert installed.exit_code == 0, installed.stdout
    plist = plistlib.loads((agents / f"{launchd.LABEL}.plist").read_bytes())
    command = plist["ProgramArguments"][2]
    assert f"--config {config_file}" in command
    assert f"{Path(sys.prefix)}/bin/sb run --if-due" in command  # the environment that is running
    assert plist["StandardOutPath"] == str(vault.root / ".esbi" / "logs" / "nightly.log")
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}  # the default
    assert "loaded: yes" in runner.invoke(app, ["schedule", "status", *where]).stdout

    removed = runner.invoke(app, ["schedule", "uninstall", *where])
    assert removed.exit_code == 0 and not (agents / f"{launchd.LABEL}.plist").exists()
    assert "loaded: no" in runner.invoke(app, ["schedule", "status", *where]).stdout


def test_schedule_install_shows_launchctl_errors_and_fails(tmp_path, config_file, monkeypatch):
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(fail="Bootstrap failed: 5"))

    result = CliRunner().invoke(
        app,
        ["schedule", "install", "--config", str(config_file), "--agents-dir", str(tmp_path)],
    )

    assert result.exit_code == 1 and "Bootstrap failed: 5" in result.output


def _mail(subject, msgid):
    from test_mail_convert import raw_email

    return raw_email(subject=subject, msgid=msgid)


def test_email_fetch_saves_recent_mail_into_the_inbox(vault, config_file, monkeypatch):
    client = FakeMailClient(
        ("1", _mail("Primero", "<a@x.test>")), ("2", _mail("Segundo", "<b@x.test>"))
    )
    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: client)

    result = CliRunner().invoke(app, ["email", "fetch", "--config", str(config_file)])

    assert result.exit_code == 0, result.stdout
    assert "Mail: 2 saved" in result.stdout and client.seen == ["1", "2"]
    assert sorted(p.name for p in (vault.root / "inbox").glob("*.md")) == [
        "2026-09-29 Primero.md",
        "2026-09-29 Segundo.md",
    ]


def test_email_fetch_refuses_to_run_when_email_is_disabled(tmp_path, vault, config_file):
    off = tmp_path / "off.toml"
    off.write_text(config_file.read_text().replace("enabled = true", "enabled = false"))

    result = CliRunner().invoke(app, ["email", "fetch", "--config", str(off)])

    assert result.exit_code == 1 and "disabled" in result.output


def test_set_password_prompts_hidden_and_stores_it_in_the_keychain(config_file, monkeypatch):
    keychain = FakeKeyring()
    monkeypatch.setattr(credentials, "keyring", keychain)

    result = CliRunner().invoke(
        app, ["email", "set-password", "--config", str(config_file)], input="abcd efgh ijkl mnop\n"
    )

    assert result.exit_code == 0, result.output
    assert keychain.store == {("esbi-cli-imap", "me@example.test"): "abcdefghijklmnop"}
    assert "abcd" not in result.output  # the password is never echoed


def test_run_fetches_mail_before_scanning_and_a_mail_outage_does_not_stop_the_run(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan(title="Primero")))
    monkeypatch.setattr(
        cli, "make_mail_client", lambda _cfg: FakeMailClient(("1", _mail("Primero", "<a@x.test>")))
    )
    runner = CliRunner()

    run = runner.invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.output
    assert "Mail: 1 saved" in run.stdout and "ingested: 1" in run.stdout
    assert vault.page_path("sources", "Primero").exists()

    class Down:
        uidvalidity = None

        def recent(self, days=14, after_uid=None):
            raise MailError("imap.example.test unreachable")

        def mark_seen(self, uid):
            raise AssertionError

        def close(self):
            pass

    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: Down())
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    again = runner.invoke(app, ["run", "--config", str(config_file)])
    assert again.exit_code == 0 and "unreachable" in again.output


def test_run_survives_an_unavailable_keychain_and_still_ingests(vault, config_file, monkeypatch):
    """CI regression: on a machine without a usable keyring, mail must be skipped, not fatal."""

    class NoKeychain:
        def get_password(self, service, user):
            raise keyring.errors.NoKeyringError("No recommended backend was available.")

    monkeypatch.setattr(credentials, "keyring", NoKeychain())
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)

    run = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.output
    assert "mail skipped" in run.output and "ingested: 1" in run.stdout


def _harness_wiki(vault):
    from test_ask import wiki_with_harness

    wiki_with_harness(vault)


def _answer_plan(**overrides):
    from test_ask import plan

    return plan(**overrides)


def test_lint_reports_problems_writes_the_report_and_clears_it_when_clean(vault, config_file):
    from test_lint import add_page

    add_page(vault, "concepts", "Suelto")
    runner = CliRunner()

    dirty = runner.invoke(app, ["lint", "--config", str(config_file)])

    assert dirty.exit_code == 0, dirty.output
    assert "orphan: 1" in dirty.stdout and (vault.wiki / "review" / "Lint.md").exists()

    vault.page_path("concepts", "Suelto").unlink()
    clean = runner.invoke(app, ["lint", "--config", str(config_file)])
    assert "No problems found" in clean.stdout and not (vault.wiki / "review" / "Lint.md").exists()


def test_ask_prints_a_cited_answer_and_saves_it_only_with_save(vault, config_file, monkeypatch):
    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan(), _answer_plan()))
    runner = CliRunner()
    args = ["ask", "¿Qué es un arnés de agente?", "--config", str(config_file)]

    shown = runner.invoke(app, args)

    assert shown.exit_code == 0, shown.output
    assert "capa de código" in shown.stdout and "Sources: [[Arnés de agente]]" in shown.stdout
    assert list((vault.wiki / "syntheses").glob("*.md")) == []

    saved = runner.invoke(app, [*args, "--save"])
    assert saved.exit_code == 0 and "Saved" in saved.stdout
    assert vault.page_path("syntheses", "Qué es un arnés de agente").exists()
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True
    ).stdout
    assert "ask: Qué es un arnés de agente" in log


def test_ask_uses_the_embed_model_only_when_the_config_has_one(vault, config_file, monkeypatch):
    _harness_wiki(vault)
    embedder = FakeEmbedder()
    built = []
    monkeypatch.setattr(cli, "make_embedder", lambda cfg: built.append(cfg.model) or embedder)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan(), _answer_plan()))
    args = ["ask", "¿Qué es un arnés de agente?", "--config", str(config_file)]

    CliRunner().invoke(app, args)
    assert built == [] and embedder.queries == []  # off by default: nothing changes

    config_file.write_text(
        config_file.read_text() + '\n[llm.embed]\nmodel = "ollama/nomic-embed-text"\n'
    )
    shown = CliRunner().invoke(app, args)

    assert shown.exit_code == 0, shown.output
    assert built == ["ollama/nomic-embed-text"] and embedder.queries == [
        "¿Qué es un arnés de agente?"
    ]


def test_an_embed_model_from_a_provider_that_cannot_embed_is_a_clear_error(vault, config_file):
    config_file.write_text(config_file.read_text() + '\n[llm.embed]\nmodel = "openai/x"\n')

    shown = CliRunner().invoke(app, ["ask", "¿Algo?", "--config", str(config_file)])

    assert shown.exit_code == 1 and "ollama" in shown.output


def test_ask_admits_when_the_wiki_has_nothing_and_does_not_save(vault, config_file, monkeypatch):
    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    result = CliRunner().invoke(
        app, ["ask", "¿Cómo se hace una tortilla?", "--save", "--config", str(config_file)]
    )

    assert result.exit_code == 0 and "No encuentro nada" in result.stdout
    assert list((vault.wiki / "syntheses").glob("*.md")) == []


def test_ask_uses_the_ask_model_when_configured_else_the_summarize_one(
    tmp_path, vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    models = []
    monkeypatch.setattr(cli, "make_llm", lambda llm_cfg: models.append(llm_cfg.model) or FakeLLM())
    runner = CliRunner()
    question = ["ask", "¿Qué es un arnés de agente?"]

    runner.invoke(app, [*question, "--config", str(config_file)])
    with_ask = tmp_path / "with-ask.toml"
    with_ask.write_text(config_file.read_text() + '\n[llm.ask]\nmodel = "ollama/bigger"\n')
    runner.invoke(app, [*question, "--config", str(with_ask)])

    assert models == ["ollama/fake", "ollama/bigger"]


def test_run_lints_the_wiki_and_the_daily_index_lists_the_report(vault, config_file, monkeypatch):
    from test_lint import add_page

    add_page(vault, "concepts", "Suelto")
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    run = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.output
    assert "Lint:" in run.stdout and (vault.wiki / "review" / "Lint.md").exists()
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "[[Lint]]" in note.read_text(encoding="utf-8")


def _bench_vault(vault):
    from test_bench_cases import write_raw

    _harness_wiki(vault)
    write_raw(vault, "2026-09-29-fuente", "Fuente de prueba", "El arnés de agente orquesta. " * 40)


def _wiki_snapshot(vault):
    return {str(p): p.read_bytes() for p in sorted((vault.root / "wiki").rglob("*")) if p.is_file()}


def test_bench_compares_the_models_reports_them_and_never_touches_the_wiki(
    vault, config_file, monkeypatch
):
    _bench_vault(vault)
    seen = {}
    fakes = {
        "ollama/good": FakeLLM(make_plan(), _answer_plan()),
        "openai/down": FakeLLM(),
    }

    def fake_make_llm(llm_cfg):
        seen[llm_cfg.model] = llm_cfg
        if llm_cfg.model == "openai/down":
            raise LLMError("openai/down: no API key")
        return fakes[llm_cfg.model]

    monkeypatch.setattr(cli, "make_llm", fake_make_llm)
    before = _wiki_snapshot(vault)

    result = CliRunner().invoke(
        app,
        [
            "bench",
            "--models",
            "ollama/good,openai/down",
            "--cases",
            "1",
            "--config",
            str(config_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "| ollama/good |" in result.stdout and "| openai/down |" in result.stdout
    assert "ingest → `ollama/good`" in result.stdout
    assert _wiki_snapshot(vault) == before
    [report] = (vault.root / ".esbi" / "bench").glob("*.md")
    assert "ollama/good" in report.read_text(encoding="utf-8")
    assert seen["ollama/good"].num_ctx == 8192  # settings inherited from [llm.summarize]


def test_bench_takes_its_models_from_config_and_fails_clearly_without_any(
    tmp_path, vault, config_file, monkeypatch
):
    _bench_vault(vault)
    runner = CliRunner()

    none = runner.invoke(app, ["bench", "--config", str(config_file)])
    assert none.exit_code == 1 and "[bench].models" in none.output

    with_models = tmp_path / "bench.toml"
    with_models.write_text(
        config_file.read_text() + '\n[bench]\nmodels = ["ollama/cfg"]\ncases = 1\n'
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan(), _answer_plan()))
    ok = runner.invoke(app, ["bench", "--config", str(with_models)])
    assert ok.exit_code == 0 and "| ollama/cfg |" in ok.stdout


def test_run_passes_the_queued_capture_date_through_to_the_source_note(
    tmp_path, vault, config_file, monkeypatch
):
    from esbi_cli.queue import Queue

    clip = tmp_path / "Guardado antes.md"
    clip.write_text(
        "---\nsource: https://x.test/old\ntitle: Arnés de agentes\n---\n" + "Texto del post. " * 10
    )
    Queue(vault.root / ".esbi" / "queue.sqlite3").add(
        str(clip), origin="legacy", captured=date(2026, 8, 31)
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))

    run = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0, run.output
    meta = vault.read_page(vault.page_path("sources", "Arnés de agentes")).meta
    assert meta["captured"] == "2026-08-31" and meta["processed"] == date.today().isoformat()


def test_retry_requeues_parked_sources_and_drop_removes_one_for_good(vault, config_file):
    from test_queue import park

    from esbi_cli.queue import Queue

    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    park(queue, "https://x.test/a")
    park(queue, "https://x.test/b")
    queue.add("https://x.test/c", origin="inbox")
    runner = CliRunner()
    args = ["--config", str(config_file)]

    one = runner.invoke(app, ["retry", "https://x.test/a", *args])
    assert one.exit_code == 0 and "Requeued 1" in one.stdout

    everything = runner.invoke(app, ["retry", *args])
    assert everything.exit_code == 0 and "Requeued 1" in everything.stdout  # only b was left parked
    assert "Nothing to retry" in runner.invoke(app, ["retry", *args]).stdout

    dropped = runner.invoke(app, ["drop", "https://x.test/c?utm_source=x", *args])
    assert dropped.exit_code == 0 and "Dropped" in dropped.stdout
    status = runner.invoke(app, ["status", *args]).stdout
    assert "queued: 2" in status and "failed: 0" in status

    unknown = runner.invoke(app, ["drop", "https://x.test/never", *args])
    assert unknown.exit_code == 1 and "not in the queue" in unknown.output


def test_add_queues_urls_and_files_without_running_anything(tmp_path, vault, config_file):
    from esbi_cli.queue import Queue

    pdf = tmp_path / "Paper Final.pdf"
    pdf.write_bytes(b"%PDF")
    note = tmp_path / "idea.md"
    note.write_text("una idea")

    result = CliRunner().invoke(
        app,
        ["add", "https://x.test/a?utm_source=z", str(pdf), str(note), "https://x.test/a"]
        + ["--config", str(config_file)],
    )

    assert result.exit_code == 0, result.output
    assert "Queued 3" in result.stdout and "1 already" in result.stdout
    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    assert queue.counts() == {"queued": 3}
    assert queue.get(str(pdf)).label == "Paper Final"


def test_add_rejects_bad_targets_and_queues_nothing(vault, config_file):
    from esbi_cli.queue import Queue

    result = CliRunner().invoke(
        app,
        [
            "add",
            "https://ok.test/x",
            "/no/such/file.pdf",
            "ftp://x.test/f",
            "--config",
            str(config_file),
        ],
    )

    assert result.exit_code == 1
    assert "/no/such/file.pdf" in result.output and "ftp://x.test/f" in result.output
    assert Queue(vault.root / ".esbi" / "queue.sqlite3").counts() == {}  # all or nothing


def test_today_builds_the_note_if_missing_and_opens_it_in_obsidian(vault, config_file, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "open_uri", opened.append)
    day = date.today().isoformat()

    result = CliRunner().invoke(app, ["today", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert (vault.wiki / "daily" / f"{day}.md").exists()
    expected = (
        f"obsidian://open?vault=vault&file=wiki%2Fdaily%2F{day}"  # the temp vault is named "vault"
    )
    assert opened == [expected] and expected in result.stdout


def test_today_opens_an_existing_note_without_rewriting_it(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "open_uri", lambda uri: None)
    note = write_daily(vault, date.today().isoformat(), "mi nota, tal cual")

    CliRunner().invoke(app, ["today", "--config", str(config_file)])

    assert note.read_text() == "mi nota, tal cual"


def menu(config_file, keys):
    """Run the interactive menu (bare `sb`) feeding it these keystrokes, one per line."""
    return CliRunner().invoke(
        app, [], input="\n".join(keys) + "\n", env={"ESBI_CONFIG": str(config_file)}
    )


def test_bare_sb_shows_a_numbered_menu_and_a_choice_runs_the_real_command(vault, config_file):
    result = menu(config_file, ["1", "q"])

    assert result.exit_code == 0, result.output
    for label in (
        "Queue status",
        "Run now",
        "Ask the wiki",
        "Add",
        "today's note",
        "lint",
        "doctor",
    ):
        assert label.lower() in result.stdout.lower(), label
    assert "queued: 0" in result.stdout  # option 1 ran `sb status`


def test_menu_choices_ask_for_their_input_and_pass_it_on(vault, config_file, monkeypatch):
    from esbi_cli.queue import Queue

    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan()))

    added = menu(config_file, ["4", "https://x.test/a https://x.test/b", "q"])
    assert added.exit_code == 0 and "Queued 2" in added.stdout
    assert Queue(vault.root / ".esbi" / "queue.sqlite3").counts() == {"queued": 2}

    asked = menu(config_file, ["3", "¿Qué es un arnés de agente?", "q"])
    assert "capa de código" in asked.stdout and "Sources:" in asked.stdout


def test_the_menu_survives_a_bad_choice_and_a_failing_command(vault, config_file):
    result = menu(config_file, ["9", "4", "/no/such/file.pdf", "q"])

    assert result.exit_code == 0, result.output
    assert "Not an option" in result.stdout
    assert "/no/such/file.pdf" in result.output  # the error from `sb add` was shown, menu went on


def test_add_says_when_a_link_is_already_in_the_wiki_instead_of_queueing_it_again(
    vault, config_file
):
    from esbi_cli.queue import Queue
    from esbi_cli.vault import Page

    vault.write_page(
        Page(
            vault.page_path("sources", "Ya está en la wiki"),
            {"title": "Ya está en la wiki", "url": "https://x.test/post?utm_source=mail"},
            "# Ya está en la wiki",
        )
    )

    result = CliRunner().invoke(
        app, ["add", "https://x.test/post/", "https://x.test/new", "--config", str(config_file)]
    )

    assert result.exit_code == 0, result.output
    assert "Queued 1" in result.stdout
    assert "already in the wiki" in result.stdout and "Ya está en la wiki" in result.stdout
    assert Queue(vault.root / ".esbi" / "queue.sqlite3").counts() == {"queued": 1}


def test_scan_reports_files_that_were_already_captured(vault, config_file):
    runner = CliRunner()
    for _ in range(2):
        (vault.root / "inbox" / "paper.pdf").write_bytes(b"%PDF same bytes")
        result = runner.invoke(app, ["scan", "--config", str(config_file)])

    assert "Queued 0" in result.stdout and "1 duplicate" in result.stdout


def test_run_uses_the_synthesis_model_for_the_digest_when_one_is_configured(
    tmp_path, vault, config_file, monkeypatch
):
    with_synth = tmp_path / "synth.toml"
    with_synth.write_text(config_file.read_text() + '\n[llm.synthesize]\nmodel = "ollama/strong"\n')
    fakes = {"ollama/fake": FakeLLM(), "ollama/strong": FakeLLM(make_plan())}
    monkeypatch.setattr(cli, "make_llm", lambda llm_cfg: fakes[llm_cfg.model])
    _clip(vault)

    run = CliRunner().invoke(app, ["run", "--config", str(with_synth)])

    assert run.exit_code == 0, run.output
    assert "ingested: 1" in run.stdout
    assert fakes["ollama/fake"].calls == [] and len(fakes["ollama/strong"].calls) == 1
    assert "(100 tokens)" in run.stdout  # tokens of both models are counted


def test_reingest_rebuilds_old_notes_from_raw_after_tagging_the_vault(
    vault, config_file, monkeypatch
):
    old = FakeLLM(make_plan())
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: old)
    _clip(vault)
    assert CliRunner().invoke(app, ["run", "--config", str(config_file)]).exit_code == 0
    note = vault.read_page(vault.page_path("sources", "Arnés de agentes"))
    note.meta.pop("format")  # as if written by an older version
    vault.write_page(note)
    new = FakeLLM(
        make_plan(summary="Un resumen ejecutivo nuevo y mucho más completo que el viejo.")
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: new)

    result = CliRunner().invoke(app, ["reingest", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert "rebuilt: 1" in result.stdout and "pre-reingest-" in result.stdout
    rebuilt = vault.read_page(vault.page_path("sources", "Arnés de agentes"))
    assert "resumen ejecutivo nuevo" in rebuilt.body and rebuilt.meta["format"] == 2
    tags = subprocess.run(["git", "tag"], cwd=vault.root, capture_output=True, text=True).stdout
    assert "pre-reingest-" in tags


def test_reingest_stops_with_an_error_when_the_model_is_down_and_says_how_to_resume(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    CliRunner().invoke(app, ["run", "--config", str(config_file)])
    note = vault.read_page(vault.page_path("sources", "Arnés de agentes"))
    note.meta.pop("format")
    vault.write_page(note)

    class Down:
        tokens_used = 0

        def complete_json(self, **_):
            raise LLMError("ollama unreachable")

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: Down())
    result = CliRunner().invoke(app, ["reingest", "--config", str(config_file)])

    assert result.exit_code == 1 and "run `sb reingest` again" in result.output
    assert (
        "El artículo explica"
        in vault.read_page(vault.page_path("sources", "Arnés de agentes")).body
    )  # untouched


def test_a_nightly_log_that_grew_large_is_cut_to_its_recent_end_at_the_start_of_a_run(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    log = vault.root / ".esbi" / "logs" / "nightly.log"
    log.parent.mkdir(parents=True)
    old = "".join(f"line {n}\n" for n in range(200_000))  # ~2 MB
    log.write_text(old)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    text = log.read_text()
    assert len(text) < 400_000 and text.endswith("line 199999\n")  # the end is what is kept
    assert text.startswith("line ")  # and it starts at a whole line


def test_init_creates_a_working_vault_and_config_and_never_overwrites_what_exists(tmp_path):
    vault_dir, config = tmp_path / "MyBrain", tmp_path / "cfg" / "config.toml"
    args = ["init", "--vault", str(vault_dir), "--config-file", str(config)]

    first = CliRunner().invoke(app, args)

    assert first.exit_code == 0, first.output
    from esbi_cli.config import load_config
    from esbi_cli.vault import Vault

    Vault(vault_dir).validate()  # SCHEMA.md and wiki/ are there
    assert (vault_dir / ".git").is_dir() and (vault_dir / "inbox").is_dir()
    assert ".esbi/" in (vault_dir / ".gitignore").read_text()
    assert load_config(config).vault == vault_dir.resolve()
    assert "sb doctor" in first.stdout  # tells what to do next

    (vault_dir / "SCHEMA.md").write_text("# mine\n")
    config.write_text(config.read_text() + "\n# my own edit\n")
    second = CliRunner().invoke(app, args)

    assert second.exit_code == 0 and (vault_dir / "SCHEMA.md").read_text() == "# mine\n"
    assert "# my own edit" in config.read_text()


def test_set_password_can_read_the_password_from_a_pipe_for_pasting_from_the_clipboard(
    config_file, monkeypatch
):
    keychain = FakeKeyring()
    monkeypatch.setattr(credentials, "keyring", keychain)
    args = ["email", "set-password", "--stdin", "--config", str(config_file)]

    result = CliRunner().invoke(app, args, input="wxyz abcd efgh ijkl\n")

    assert result.exit_code == 0, result.output
    assert keychain.store == {("esbi-cli-imap", "me@example.test"): "wxyzabcdefghijkl"}
    assert "wxyz" not in result.output

    empty = CliRunner().invoke(app, args, input="\n")
    assert empty.exit_code == 1 and "empty" in empty.output


def test_run_sends_an_email_to_the_private_model_even_when_the_main_model_is_a_subscription(
    tmp_path, vault, config_file, monkeypatch
):
    private_cfg = tmp_path / "private.toml"
    private_cfg.write_text(
        config_file.read_text().replace("ollama/fake", "claude-cli/default")
        + '\n[llm.private]\nmodel = "ollama/local"\n'
    )
    cloud, local = FakeLLM(), FakeLLM(make_plan())
    cloud.sends_text_out = True
    fakes = {"claude-cli/default": cloud, "ollama/local": local}
    monkeypatch.setattr(cli, "make_llm", lambda llm_cfg: fakes[llm_cfg.model])
    (vault.root / "inbox" / "Mail.md").write_text(
        "---\nsource: mail:abc@x.test\nkind: email\ntitle: Asunto\n---\n" + "Texto privado. " * 20
    )

    run = CliRunner().invoke(app, ["run", "--config", str(private_cfg)])

    assert run.exit_code == 0, run.output
    assert "ingested: 1" in run.stdout and cloud.calls == [] and len(local.calls) == 1


def test_schedule_install_uses_the_time_from_the_config_and_says_which(
    tmp_path, vault, config_file, monkeypatch
):
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl())
    timed = tmp_path / "timed.toml"
    timed.write_text(config_file.read_text().replace("[run]", '[run]\nnightly_time = "05:15"'))
    agents = tmp_path / "LaunchAgents"

    result = CliRunner().invoke(
        app, ["schedule", "install", "--config", str(timed), "--agents-dir", str(agents)]
    )

    assert result.exit_code == 0, result.output
    plist = plistlib.loads((agents / f"{launchd.LABEL}.plist").read_bytes())
    assert plist["StartCalendarInterval"] == {"Hour": 5, "Minute": 15}
    assert "05:15" in result.stdout


def test_run_if_due_asks_for_the_configured_boundary(tmp_path, vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())
    seen = []
    monkeypatch.setattr(cli, "is_due", lambda runs, now, at, **_: seen.append(at) or False)
    late = tmp_path / "late.toml"
    late.write_text(config_file.read_text().replace("[run]", '[run]\nnightly_time = "23:59"'))

    CliRunner().invoke(app, ["run", "--if-due", "--config", str(late)])

    assert seen == [(23, 59)]


def test_set_password_failure_is_a_message_and_not_a_traceback(config_file, monkeypatch):
    class Refusing:
        def set_password(self, service, user, password):
            raise keyring.errors.PasswordSetError("denied (-25244)")

    monkeypatch.setattr(credentials, "keyring", Refusing())

    result = CliRunner().invoke(
        app, ["email", "set-password", "--stdin", "--config", str(config_file)], input="abcd\n"
    )

    assert result.exit_code == 1
    assert "security delete-generic-password" in result.output and "Traceback" not in result.output


def test_every_question_is_logged_with_what_was_retrieved_and_whether_it_was_grounded(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan(), _answer_plan()))
    runner = CliRunner()

    runner.invoke(app, ["ask", "¿Qué es un arnés de agente?", "--config", str(config_file)])
    runner.invoke(app, ["ask", "¿Cómo se hace una tortilla?", "--config", str(config_file)])

    rows = [
        json.loads(line) for line in (vault.root / ".esbi" / "asks.jsonl").read_text().splitlines()
    ]
    assert [r["grounded"] for r in rows] == [True, False]
    assert (
        "Arnés de agente" in rows[0]["retrieved"]
        and rows[0]["cited"]
        == ["Arnés de agente", "Code as Agent Harness"][: len(rows[0]["cited"])]
    )
    assert rows[0]["question"] == "¿Qué es un arnés de agente?" and rows[0]["seconds"] >= 0
    assert rows[1]["retrieved"] == [] and "tokens" in rows[0]


def test_without_obsidian_today_prints_the_path_of_the_note_and_opens_nothing(
    tmp_path, vault, config_file, monkeypatch
):
    opened = []
    monkeypatch.setattr(cli, "open_uri", lambda uri: opened.append(uri))
    plain = tmp_path / "plain.toml"
    plain.write_text(
        config_file.read_text().replace('language = "es"', 'language = "es"\nviewer = "none"')
    )
    write_daily(vault, date.today().isoformat(), "mi nota")

    result = CliRunner().invoke(app, ["today", "--config", str(plain)])

    assert result.exit_code == 0, result.output
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert str(note) in result.stdout and "obsidian://" not in result.stdout and opened == []


def test_init_can_set_the_model_kind_and_says_what_leaves_the_machine(tmp_path, monkeypatch):
    from esbi_cli.config import load_config

    vault_dir = tmp_path / "Brain"

    def init(model, name):
        config = tmp_path / name / "config.toml"
        args = ["init", "--vault", str(vault_dir), "--config-file", str(config), "--model", model]
        return CliRunner().invoke(app, args), config

    local, local_cfg = init("local", "a")
    assert local.exit_code == 0 and "stays on this Mac" in local.stdout
    assert load_config(local_cfg).llm["summarize"].model.startswith("ollama/")

    sub, sub_cfg = init("subscription", "b")
    cfg = load_config(sub_cfg)
    assert sub.exit_code == 0 and "your Claude subscription" in sub.stdout
    assert cfg.llm["summarize"].model == "claude-cli/default"
    assert cfg.llm["summarize"].fallback and cfg.llm["private"].model.startswith(
        "ollama/"
    )  # email stays local

    api, api_cfg = init("api", "c")
    cfg = load_config(api_cfg)
    assert api.exit_code == 0 and "ANTHROPIC_API_KEY" in api.stdout
    assert cfg.llm["summarize"].model.startswith("anthropic/") and "private" in cfg.llm

    bad, _ = init("telepathy", "d")
    assert bad.exit_code == 1 and "local, subscription or api" in bad.output


def test_init_can_connect_the_vault_to_a_backup_remote_without_overwriting_one(tmp_path):
    bare = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    vault_dir = tmp_path / "Brain"
    args = ["init", "--vault", str(vault_dir), "--config-file", str(tmp_path / "c.toml")]

    first = CliRunner().invoke(app, [*args, "--remote", str(bare)])
    other = CliRunner().invoke(app, [*args, "--remote", str(tmp_path / "otro.git")])

    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=vault_dir, capture_output=True, text=True
    ).stdout.strip()
    assert first.exit_code == 0 and url == str(bare)
    assert "already has a remote" in other.stdout and url == str(bare)  # left alone
    assert "private" in first.stdout  # the remote receives notes made from email too


def test_info_prints_the_facts_the_wizards_need_as_key_value_lines(vault, config_file):
    result = CliRunner().invoke(app, ["info", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    facts = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert facts["vault"] == str(vault.root) and facts["config"] == str(config_file)
    assert facts["viewer"] == "obsidian" and facts["email"] == "enabled"


def test_email_configure_writes_the_mailbox_block_and_leaves_everything_else(
    tmp_path, vault, config_file
):
    from esbi_cli.config import load_config

    bare = tmp_path / "bare.toml"
    bare.write_text(config_file.read_text().split("[email]")[0], encoding="utf-8")
    assert load_config(bare).email.enabled is False
    args = ["email", "configure", "--config", str(bare), "--user", "ana@gmail.com"]

    first = CliRunner().invoke(app, args)
    again = CliRunner().invoke(app, [*args, "--label", "Otra"])

    assert first.exit_code == 0 and again.exit_code == 0, first.output + again.output
    cfg = load_config(bare)
    assert (cfg.email.enabled, cfg.email.user, cfg.email.mailbox) == (True, "ana@gmail.com", "Otra")
    assert cfg.llm["summarize"].model == "ollama/fake"  # the rest of the file is untouched
    assert bare.read_text().count("[email]") == 1


def test_email_configure_keeps_the_link_following_choices_already_made(tmp_path, config_file):
    from esbi_cli.config import load_config

    config_file.write_text(config_file.read_text() + "follow_links = true\nfollow_links_max = 5\n")

    result = CliRunner().invoke(
        app, ["email", "configure", "--config", str(config_file), "--user", "ana@gmail.com"]
    )

    assert result.exit_code == 0, result.output
    email = load_config(config_file).email
    assert (email.user, email.follow_links, email.follow_links_max) == ("ana@gmail.com", True, 5)


def test_setup_runs_the_wizard_that_ships_in_the_package_with_what_it_needs(
    vault, config_file, monkeypatch
):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["env"]))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    for which in ("email", "clipper"):
        result = CliRunner().invoke(app, ["setup", which, "--config", str(config_file)])
        assert result.exit_code == 0, result.output

    (email_cmd, env), (clipper_cmd, _) = calls
    assert email_cmd[0] == "bash" and email_cmd[1].endswith("wizards/email.sh")
    assert clipper_cmd[1].endswith("wizards/clipper.sh") and Path(clipper_cmd[1]).is_file()
    assert env["SB_CONFIG"] == str(config_file) and Path(env["SB_TEMPLATES"]).is_dir()
    assert Path(env["SB"]).name == "sb"


def test_the_wizards_are_valid_bash_and_no_longer_need_a_source_checkout():
    wizards = Path(cli.__file__).parent / "wizards"
    for script in wizards.glob("*.sh"):
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0, script.name
        text = script.read_text()
        assert "uv run" not in text and "config.example.toml" not in text, script.name


def _init(tmp_path, *extra, input=None):
    config = tmp_path / "cfg" / "config.toml"
    args = ["init", "--vault", str(tmp_path / "Brain"), "--config-file", str(config), *extra]
    return CliRunner().invoke(app, args, input=input), config


def test_init_flags_choose_obsidian_the_local_runtime_and_the_nightly_time(tmp_path, monkeypatch):
    from esbi_cli.config import load_config

    launchctl = FakeLaunchctl()
    monkeypatch.setattr(launchd, "run_launchctl", launchctl)
    monkeypatch.setattr(cli, "AGENTS_DIR", tmp_path / "LaunchAgents")
    monkeypatch.setattr(cli.sys, "platform", "darwin")  # the job is only installed on macOS

    result, config = _init(
        tmp_path,
        "--no-obsidian",
        "--runtime",
        "lmstudio",
        "--local-model",
        "qwen2.5-7b",
        "--nightly",
        "04:30",
    )

    assert result.exit_code == 0, result.output
    cfg = load_config(config)
    assert cfg.viewer == "none" and cfg.nightly_time == "04:30"
    assert cfg.llm["summarize"].model == "lmstudio/qwen2.5-7b"
    plist = plistlib.loads((tmp_path / "LaunchAgents" / f"{launchd.LABEL}.plist").read_bytes())
    assert plist["StartCalendarInterval"] == {"Hour": 4, "Minute": 30}  # the job follows the choice


def test_init_does_not_install_the_nightly_job_unless_asked_and_lm_studio_needs_a_model_name(
    tmp_path, monkeypatch
):
    launchctl = FakeLaunchctl()
    monkeypatch.setattr(launchd, "run_launchctl", launchctl)
    monkeypatch.setattr(cli, "AGENTS_DIR", tmp_path / "LaunchAgents")

    plain, _ = _init(tmp_path)
    assert plain.exit_code == 0 and launchctl.calls == []

    missing, _ = _init(tmp_path / "x", "--runtime", "lmstudio")
    assert missing.exit_code == 1 and "--local-model" in missing.output


def test_the_interactive_installer_asks_what_you_use_and_marks_everything_optional(
    tmp_path, monkeypatch
):
    from esbi_cli.config import load_config

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    wizards = []
    monkeypatch.setattr(cli, "_run_wizard", lambda script, config: wizards.append(script))
    answers = "\n".join(
        [
            "1",  # notes language: English
            "n",  # do you use Obsidian?
            "1",  # models: local
            "1",  # runtime: Ollama
            "",  # server address: this Mac
            "n",  # run every night?
            "",  # backup remote: skip
            "n",  # read images?
            "y",  # connect Gmail?
        ]
    )

    result, config = _init(tmp_path, input=answers + "\n")

    assert result.exit_code == 0, result.output
    cfg = load_config(config)
    assert cfg.viewer == "none" and cfg.llm["summarize"].model.startswith("ollama/")
    assert "optional" in result.stdout.lower() and "PDFs" in result.stdout
    assert "needs Obsidian" in result.stdout  # the Clipper is explained, not offered
    assert wizards == ["email.sh"]


def test_the_interactive_installer_offers_the_clipper_to_people_with_obsidian(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    wizards = []
    monkeypatch.setattr(cli, "_run_wizard", lambda script, config: wizards.append(script))
    answers = "\n".join(
        ["1", "y", "1", "1", "", "n", "", "n", "n", "y"]
    )  # English; Obsidian yes; ...; images no; Gmail no; Clipper yes

    result, _ = _init(tmp_path, input=answers + "\n")

    assert result.exit_code == 0, result.output
    assert wizards == ["clipper.sh"]


def test_init_warns_when_the_local_runtime_is_on_another_machine(tmp_path):
    from esbi_cli.config import load_config

    result, config = _init(tmp_path, "--base-url", "http://gpu-box.lan:11434")

    assert result.exit_code == 0, result.output
    assert load_config(config).llm["summarize"].base_url == "http://gpu-box.lan:11434"
    assert "gpu-box.lan" in result.output and "email is kept off it" in result.output

    here, here_config = _init(tmp_path / "x", "--base-url", "http://127.0.0.1:11434")
    assert here.exit_code == 0, here.output
    assert load_config(here_config).llm["summarize"].base_url == "http://127.0.0.1:11434"
    assert "not this machine" not in here.output


def test_init_refuses_a_base_url_it_cannot_use(tmp_path):
    cloud, _ = _init(tmp_path, "--model", "api", "--base-url", "http://gpu-box.lan:11434")
    junk, _ = _init(tmp_path / "x", "--base-url", "not a url")

    assert cloud.exit_code == 1 and "--base-url" in cloud.output
    assert junk.exit_code == 1 and "--base-url" in junk.output


def test_the_interactive_installer_warns_when_you_type_a_server_on_another_machine(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_run_wizard", lambda script, config: None)
    answers = ["1", "n", "1", "1", "http://gpu-box.lan:11434", "n", "", "n", "n"]

    result, _ = _init(tmp_path, input="\n".join(answers) + "\n")

    assert result.exit_code == 0, result.output
    assert "gpu-box.lan" in result.output and "email is kept off it" in result.output


def test_an_unsupported_notes_language_is_an_error_line_and_not_a_traceback(config_file):
    config_file.write_text(
        config_file.read_text().replace('language = "es"', 'language = "fr"'), encoding="utf-8"
    )
    result = CliRunner().invoke(app, ["status", "--config", str(config_file)])
    assert result.exit_code == 1
    assert "error: [notes].language must be one of: en, es" in result.output
    assert "Traceback" not in result.output


def test_init_asks_for_the_notes_language_with_a_flag_and_says_the_cli_stays_english(tmp_path):
    root, config = tmp_path / "v", tmp_path / "c.toml"
    result = CliRunner().invoke(
        app, ["init", "--vault", str(root), "--config-file", str(config), "--language", "es"]
    )
    assert result.exit_code == 0, result.output
    assert 'language = "es"' in config.read_text()
    assert "Spanish" in (root / "SCHEMA.md").read_text()
    assert (root / "index.md").read_text().startswith("# Índice")
    assert (
        "Notes language: es (Spanish)" in result.output and "CLI itself is English" in result.output
    )


def test_init_writes_english_notes_by_default_and_refuses_an_unknown_language(tmp_path):
    root, config = tmp_path / "v", tmp_path / "c.toml"
    done = CliRunner().invoke(app, ["init", "--vault", str(root), "--config-file", str(config)])
    assert done.exit_code == 0, done.output
    assert 'language = "en"' in config.read_text()
    assert (root / "index.md").read_text().startswith("# Index")

    bad = CliRunner().invoke(
        app,
        [
            "init",
            "--vault",
            str(tmp_path / "w"),
            "--config-file",
            str(tmp_path / "d.toml"),
            "--language",
            "fr",
        ],
    )
    assert bad.exit_code == 1 and "error: --language must be one of: en, es" in bad.output


def test_info_and_doctor_show_the_language(vault, config_file):
    assert "language=es" in CliRunner().invoke(app, ["info", "--config", str(config_file)]).output


def test_a_bad_config_key_ends_every_command_in_one_error_line_and_exit_1(config_file):
    config_file.write_text(
        config_file.read_text().replace(
            'model = "ollama/fake"', 'model = "ollama/fake"\nnum_ctxx = 1'
        )
    )
    for args in (["status"], ["run"], ["ask", "q"], ["lint"], ["ingest", "https://x.test"]):
        result = CliRunner().invoke(app, [*args, "--config", str(config_file)])
        assert result.exit_code == 1, args
        assert result.exception is None or isinstance(result.exception, SystemExit), args
        assert "error: " in result.output and "num_ctxx" in result.output, args
        assert "Traceback" not in result.output, args


def test_doctor_reports_a_bad_config_key_as_a_failed_config_check(config_file):
    config_file.write_text(config_file.read_text().replace("[email]", "[email]\nenabld = true"))

    result = CliRunner().invoke(app, ["doctor", "--config", str(config_file)])

    assert result.exit_code == 1
    assert "FAIL config" in result.output and "'enabld'" in result.output


def test_a_config_path_that_does_not_exist_is_an_error_for_every_command(tmp_path, config_file):
    missing = tmp_path / "typo.toml"
    runner = CliRunner()
    for args in (
        ["status"],
        ["info"],
        ["setup", "email"],
        ["email", "configure", "--user", "a@b.c"],
    ):
        result = runner.invoke(app, [*args, "--config", str(missing)])
        assert result.exit_code == 1, args
        assert f"error: config file not found: {missing}" in result.output, args
        assert "Traceback" not in result.output, args
    doctor = runner.invoke(app, ["doctor", "--config", str(missing)])
    assert doctor.exit_code == 1 and "config file not found" in doctor.output


def test_run_says_which_sources_failed_why_and_which_are_parked(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    def ingest(target, **_):
        raise cli.ExtractError(f"no readable content\nin {target}" + " very long" * 40)

    monkeypatch.setattr(cli, "run_ingest", ingest)
    runner = CliRunner()
    runner.invoke(app, ["add", "https://x.test/a", "--config", str(config_file)])

    first = runner.invoke(app, ["run", "--config", str(config_file)])
    runner.invoke(app, ["run", "--config", str(config_file)])
    third = runner.invoke(app, ["run", "--config", str(config_file)])

    one_line = [line for line in first.stdout.splitlines() if "https://x.test/a" in line]
    assert len(one_line) == 1 and len(one_line[0]) < 260
    assert "attempt 1 of 3" in one_line[0] and "ExtractError: no readable content" in one_line[0]
    assert "parked" not in one_line[0]
    assert "failed: 1" in first.stdout  # the summary line stays
    last = [line for line in third.stdout.splitlines() if "https://x.test/a" in line][0]
    assert "attempt 3 of 3" in last and "parked" in last and "sb retry" in last
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "No se pudo procesar https://x.test/a (ExtractError: no readable content" in (
        note.read_text(encoding="utf-8")
    )  # the daily index already lists parked sources with the error


def test_schedule_commands_on_a_system_without_launchd_say_so_and_show_the_cron_line(
    tmp_path, config_file, monkeypatch
):
    def no_launchctl(args):
        raise FileNotFoundError(2, "No such file or directory", "launchctl")

    monkeypatch.setattr(launchd, "run_launchctl", no_launchctl)
    monkeypatch.setenv("ESBI_CONFIG", str(config_file))
    agents = tmp_path / "LaunchAgents"
    cron = launchd.cron_line(config_file)
    assert cron.startswith("0 * * * * /") and " run --if-due --config " in cron  # absolute `sb`

    for args in (["install", "--config", str(config_file)], ["uninstall"]):
        result = CliRunner().invoke(app, ["schedule", *args, "--agents-dir", str(agents)])

        assert result.exit_code == 1, args  # they cannot do what was asked
        assert result.exception is None or isinstance(result.exception, SystemExit), args
        assert "launchd" in result.output and "macOS" in result.output, args
        assert cron in result.output, args
    assert not agents.exists()  # a failed install leaves no half-written LaunchAgent behind


def test_schedule_status_without_launchd_is_not_an_error_and_shows_the_cron_line(
    tmp_path, config_file, monkeypatch
):
    # there is nothing to query: asking is not a failure (a script that checks the exit code)
    def no_launchctl(args):
        raise FileNotFoundError(2, "No such file or directory", "launchctl")

    monkeypatch.setattr(launchd, "run_launchctl", no_launchctl)
    monkeypatch.setenv("ESBI_CONFIG", str(config_file))

    result = CliRunner().invoke(app, ["schedule", "status", "--agents-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "only macOS has" in result.output and launchd.cron_line(config_file) in result.output
    assert not result.output.startswith("error:")


def test_init_and_the_schedule_error_print_the_same_cron_line(tmp_path, config_file):
    sb = launchd.stable_prefix(Path(sys.prefix)) / "bin" / "sb"  # the running install's `sb`
    assert launchd.cron_line(config_file) == (
        f"0 * * * * {sb} run --if-due --config {config_file.resolve()}"
    )


def _commands(group, path=()):
    """Every command of the app with the argv that reaches it."""
    for name, command in group.commands.items():
        yield (*path, name), command
        if hasattr(command, "commands"):
            yield from _commands(command, (*path, name))


def test_help_keeps_the_square_brackets_of_config_sections():
    import re

    import typer.main

    root = typer.main.get_command(app)
    section = re.compile(r"\[[a-z][a-z_.]*\]")
    checked = 0
    for path, command in [((), root), *_commands(root)]:
        shown = " ".join(CliRunner().invoke(app, [*path, "--help"]).output.split())
        wanted = [command.help or ""] + [getattr(p, "help", None) or "" for p in command.params]
        for mention in section.findall(" ".join(wanted)):
            checked += 1
            assert mention in shown, f"`sb {' '.join(path)} --help` lost {mention}"
    assert checked >= 3  # [notes], [llm.ocr] and [run] are in today's help texts


def test_a_proxy_opt_in_lasts_for_one_command_and_never_leaks_into_the_next(tmp_path, config_file):
    from esbi_cli import netguard

    opted_in = tmp_path / "proxy.toml"
    opted_in.write_text(config_file.read_text() + "\n[network]\nuse_environment_proxy = true\n")

    CliRunner().invoke(app, ["status", "--config", str(opted_in)])
    assert netguard.use_environment_proxy is True  # the config the command loaded decides

    CliRunner().invoke(app, ["version"])  # loads no config
    assert netguard.use_environment_proxy is False


def test_bench_help_names_its_config_section_with_brackets():
    shown = " ".join(CliRunner().invoke(app, ["bench", "--help"]).output.split())

    assert "[bench]" in shown and "bench section" not in shown


def test_email_fetch_says_how_many_images_were_kept_and_links_queued_only_when_there_are_some(
    vault, config_file, monkeypatch
):
    from test_mail_convert import picture, raw_email

    from esbi_cli.config import load_config

    plain = FakeMailClient(("1", _mail("Primero", "<a@x.test>")))
    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: plain)
    quiet = CliRunner().invoke(app, ["email", "fetch", "--config", str(config_file)])
    assert "Mail: 1 saved, 0 duplicates, 0 failed." in quiet.stdout

    body = "Lee https://blog.test/uno y https://blog.test/dos para entender el tema. " * 3
    rich = raw_email(body=body, msgid="<b@x.test>", images=[("Foto.png", picture(), "image/png")])
    client = FakeMailClient(("2", rich))
    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: client)
    follow = config_file.with_name("follow.toml")
    follow.write_text(config_file.read_text() + "follow_links = true\nfollow_links_max = 2\n")

    result = CliRunner().invoke(app, ["email", "fetch", "--config", str(follow)])

    assert result.exit_code == 0, result.stdout
    assert "Mail: 1 saved, 0 duplicates, 0 failed, 1 images saved, 2 links queued." in result.stdout
    queued = [(i.target, i.origin) for i in cli._open_queue(load_config(follow)).items("queued")]
    assert queued == [
        ("https://blog.test/uno", "mail-link"),
        ("https://blog.test/dos", "mail-link"),
    ]


def test_run_reads_a_link_from_a_mail_with_the_private_model_only(
    tmp_path, vault, config_file, monkeypatch
):
    from esbi_cli.config import load_config
    from esbi_cli.extract import ExtractedDoc

    private_cfg = tmp_path / "private.toml"
    private_cfg.write_text(
        config_file.read_text().replace("ollama/fake", "claude-cli/default")
        + '\n[llm.private]\nmodel = "ollama/local"\n'
    )
    cloud, local = FakeLLM(), FakeLLM(make_plan())
    cloud.sends_text_out = True
    fakes = {"claude-cli/default": cloud, "ollama/local": local}
    monkeypatch.setattr(cli, "make_llm", lambda llm_cfg: fakes[llm_cfg.model])
    page = ExtractedDoc(
        "Pagina", "Texto de una pagina publica. " * 30, "article", "https://blog.test/uno"
    )
    monkeypatch.setattr(cli, "_extractor", lambda cfg, ocr: lambda target: page)
    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: FakeMailClient())
    cli._open_queue(load_config(private_cfg)).add("https://blog.test/uno", origin="mail-link")

    run = CliRunner().invoke(app, ["run", "--config", str(private_cfg)])

    assert run.exit_code == 0, run.output
    assert "ingested: 1" in run.stdout and cloud.calls == [] and len(local.calls) == 1


def _limit_run(started: datetime) -> RunRecord:
    return RunRecord(started, started, 1, 0, 0, 10, "max_sources", "scheduled")


def test_the_hourly_tick_runs_the_next_batch_while_a_limit_stopped_run_left_items_queued(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    log = RunLog(vault.root / ".esbi" / "runs.jsonl")
    log.record(_limit_run(datetime.now().replace(hour=0, minute=1)))
    config_file.write_text(
        config_file.read_text().replace("[run]", '[run]\nnightly_time = "00:00"')
    )
    CliRunner().invoke(app, ["scan", "--config", str(config_file)])  # one source is queued

    tick = CliRunner().invoke(app, ["run", "--if-due", "--config", str(config_file)])

    assert tick.exit_code == 0 and "ingested: 1" in tick.stdout, tick.stdout
    assert [r.stopped_by for r in log.runs()] == ["max_sources", None]

    _forbid_llm(monkeypatch)  # queue drained and the last run finished: the day is done
    again = CliRunner().invoke(app, ["run", "--if-due", "--config", str(config_file)])
    assert "not due" in again.stdout.lower()


def test_the_hourly_tick_does_not_drain_an_empty_queue_nor_a_busy_lock(
    vault, config_file, monkeypatch
):
    _forbid_llm(monkeypatch)
    log = RunLog(vault.root / ".esbi" / "runs.jsonl")
    log.record(_limit_run(datetime.now().replace(hour=0, minute=1)))
    config_file.write_text(
        config_file.read_text().replace("[run]", '[run]\nnightly_time = "00:00"')
    )
    args = ["run", "--if-due", "--config", str(config_file)]

    assert "not due" in CliRunner().invoke(app, args).stdout.lower()  # nothing queued

    _clip(vault)
    CliRunner().invoke(app, ["scan", "--config", str(config_file)])
    with RunLock(vault.root / ".esbi" / "run.lock"):
        busy = CliRunner().invoke(app, args)
    assert "another run is in progress" in busy.stdout.lower()
    assert len(log.runs()) == 1


def _priced(config_file, model, *, cap_usd=50):
    """The summarize model is `model`, at 1 USD per token (the fake model uses 100 tokens a call)."""
    text = config_file.read_text().replace(
        "[run]", f"[run]\nmax_usd_per_run = {cap_usd}\nfind_connections = false"
    )
    text = text.replace('model = "ollama/fake"', f'model = "{model}"')
    config_file.write_text(text + f'\n[bench.prices]\n"{model}" = 1000000.0\n')


def _two_clips(vault):
    _clip(vault, "A.md", "https://x.test/a")
    (vault.root / "inbox" / "B.md").write_text(
        "---\nsource: https://x.test/b\ntitle: Otro título\n---\n" + "Otro texto distinto. " * 10
    )


def test_a_run_stops_at_the_usd_cap_for_a_model_that_sends_text_out(
    vault, config_file, monkeypatch
):
    cloud = FakeLLM(make_plan(), make_plan(title="Otro"))
    cloud.sends_text_out = True
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: cloud)
    _priced(config_file, "anthropic/fake")
    _two_clips(vault)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 0, result.stdout
    assert "ingested: 1" in result.stdout and "Stopped early (usd_budget)" in result.stdout
    [record] = RunLog(vault.root / ".esbi" / "runs.jsonl").runs()
    assert record.stopped_by == "usd_budget"
    assert "queued: 1" in CliRunner().invoke(app, ["status", "--config", str(config_file)]).stdout
    note = vault.wiki / "daily" / f"{date.today().isoformat()}.md"
    assert "detenida: presupuesto en USD" in note.read_text(encoding="utf-8")


def test_a_subscription_never_reaches_the_usd_cap_even_with_a_price_in_the_table(
    vault, config_file, monkeypatch
):
    flat_rate = FakeLLM(make_plan(), make_plan(title="Otro"))
    flat_rate.sends_text_out = True
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: flat_rate)
    _priced(config_file, "claude-cli/default")
    _two_clips(vault)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert "ingested: 2" in result.stdout and "usd_budget" not in result.stdout


def test_a_local_model_never_reaches_the_usd_cap(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan(), make_plan(title="Otro")))
    _priced(config_file, "ollama/fake")
    _two_clips(vault)

    assert "ingested: 2" in CliRunner().invoke(app, ["run", "--config", str(config_file)]).stdout


def test_email_fetch_says_when_the_server_would_not_mark_mail_as_read(
    vault, config_file, monkeypatch
):
    client = FakeMailClient(("1", _mail("Primero", "<a@x.test>")), accepts_seen=False)
    monkeypatch.setattr(cli, "make_mail_client", lambda _cfg: client)

    result = CliRunner().invoke(app, ["email", "fetch", "--config", str(config_file)])

    assert "1 not marked as read (the server refused)" in result.stdout


def test_open_uri_uses_open_on_macos_and_xdg_open_elsewhere(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    monkeypatch.setattr(sys, "platform", "darwin")
    cli.open_uri("obsidian://open?vault=v")
    monkeypatch.setattr(sys, "platform", "linux")
    cli.open_uri("obsidian://open?vault=v")

    assert calls == [["open", "obsidian://open?vault=v"], ["xdg-open", "obsidian://open?vault=v"]]


def test_open_uri_without_an_opener_says_so_and_does_not_fail(monkeypatch, capsys):
    def missing(cmd, **kw):
        raise FileNotFoundError(2, "No such file", cmd[0])

    monkeypatch.setattr(subprocess, "run", missing)
    monkeypatch.setattr(sys, "platform", "linux")

    cli.open_uri("obsidian://open?vault=v")  # WSL without wslu, a server

    assert "xdg-open" in capsys.readouterr().out


def test_export_help_names_the_default_folder_instead_of_losing_a_tag_like_word():
    # "<vault>/site" in a help text is rendered as a (swallowed) tag: it printed "(default: /site)"
    result = CliRunner().invoke(app, ["export", "--help"])

    assert "(default: /site)" not in result.output
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)  # CI forces colour: styled words break up
    text = " ".join(plain.replace("│", " ").split())  # the help box wraps lines
    assert "the site folder in the vault" in text


def test_a_clip_added_from_outside_the_inbox_keeps_its_unstripped_original(
    tmp_path, vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    clip = tmp_path / "Clip.md"
    clip.write_text(
        "---\nsource: https://x.test/p\ntitle: Arnés de agentes\n---\n"
        "Skip to content\n\nSign in\n\n" + "Texto del post. " * 10
    )
    runner = CliRunner()

    runner.invoke(app, ["add", str(clip), "--config", str(config_file)])
    run = runner.invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == 0 and "ingested: 1" in run.stdout, run.stdout
    assert (vault.root / "raw" / "inbox" / "Clip.md").read_bytes() == clip.read_bytes()


def test_the_hourly_tick_stops_draining_at_max_batches_per_day(vault, config_file, monkeypatch):
    _forbid_llm(monkeypatch)
    log = RunLog(vault.root / ".esbi" / "runs.jsonl")
    midnight = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0)
    for n in range(3):
        log.record(_limit_run(midnight + timedelta(seconds=n)))
    config_file.write_text(
        config_file.read_text().replace(
            "[run]", '[run]\nnightly_time = "00:00"\nmax_batches_per_day = 3'
        )
    )
    _clip(vault)
    CliRunner().invoke(app, ["scan", "--config", str(config_file)])  # a source is waiting

    tick = CliRunner().invoke(app, ["run", "--if-due", "--config", str(config_file)])

    assert "not due" in tick.stdout.lower() and len(log.runs()) == 3

    config_file.write_text(
        config_file.read_text().replace("max_batches_per_day = 3", "max_batches_per_day = 4")
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    again = CliRunner().invoke(app, ["run", "--if-due", "--config", str(config_file)])
    assert "ingested: 1" in again.stdout, again.stdout


def test_run_help_says_what_caps_the_hourly_drain():
    out = " ".join(CliRunner().invoke(app, ["run", "--help"]).stdout.split())

    assert "max_batches_per_day" in out


def _clip_file(tmp_path):
    clip = tmp_path / "Clip.md"
    clip.write_text("---\ntitle: T\n---\n" + "Texto del post. " * 10)
    return clip


def test_a_read_only_vault_is_an_error_line_not_a_traceback(
    tmp_path, vault, config_file, monkeypatch
):
    import sqlite3

    from esbi_cli.queue import Queue

    def read_only(self, *args, **kwargs):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(Queue, "add", read_only)

    result = CliRunner().invoke(
        app, ["add", str(_clip_file(tmp_path)), "--config", str(config_file)]
    )

    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert "error:" in result.output and "read-only" in result.output.lower()
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["lint", "run", "index", "scan"])
def test_any_os_error_in_a_command_is_an_error_line_with_the_path(
    vault, config_file, monkeypatch, command
):
    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(vault.root / ".esbi" / "run.lock"))

    for name in ("_lint", "_run_locked", "_refresh_index", "_open_queue"):
        monkeypatch.setattr(cli, name, denied)

    result = CliRunner().invoke(app, [command, "--config", str(config_file)])

    assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.output
    assert "error: Permission denied" in result.output and "run.lock" in result.output


def test_an_os_error_with_json_is_an_error_object_with_the_code_os_error(
    vault, config_file, monkeypatch
):
    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "/vault/.esbi/run.lock")

    monkeypatch.setattr(cli, "_run_locked", denied)

    result = CliRunner().invoke(app, ["run", "--json", "--config", str(config_file)])

    assert result.exit_code == 1
    error = json.loads(result.stdout.strip().splitlines()[-1])
    assert error["contract"] == 1 and error["code"] == "os_error"
    assert "Permission denied" in error["error"]


def test_the_program_starts_where_the_home_folder_cannot_be_found():
    # a uid with no passwd entry and no $HOME (a container, a service): `~` cannot be expanded,
    # and importing esbi_cli used to raise RuntimeError, so even `sb version` crashed
    code = (
        "import os; os.path.expanduser = lambda p: p\n"  # what expanduser does with no home
        "from typer.testing import CliRunner\n"
        "from esbi_cli.cli import app\n"
        "r = CliRunner().invoke(app, ['version'])\n"
        "print(r.exit_code, r.output.strip())\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f"0 {__version__}"


def test_init_without_a_home_folder_asks_for_explicit_paths_instead_of_a_traceback(monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: p)  # no $HOME and no passwd entry

    result = CliRunner().invoke(app, ["init"])

    assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.output
    assert result.output.startswith("error:") and "--vault" in result.output
    assert "Traceback" not in result.output


def test_a_closed_output_pipe_ends_the_command_quietly(vault, config_file, monkeypatch):
    def closed(*args, **kwargs):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(cli, "_run_locked", closed)

    result = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert "error" not in result.output.lower() and "Traceback" not in result.output


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores permissions")
def test_init_in_a_folder_it_cannot_write_says_so_in_one_line(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        result = CliRunner().invoke(
            app,
            ["init", "--vault", str(locked / "vault"), "--config-file", str(tmp_path / "c.toml")],
        )
    finally:
        locked.chmod(0o755)

    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert result.output.startswith("error: Permission denied") and "Traceback" not in result.output
