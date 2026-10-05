"""Ctrl-C and SIGTERM during `sb run`: the item in flight goes back untouched."""

import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import FakeLLM
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli.cli import app
from esbi_cli.interrupts import Interrupted, deferred, handling, interruptible
from esbi_cli.queue import Queue

CLIP = "---\nsource: https://x.test/{n}\ntitle: Fuente {n}\n---\n" + "Texto del post. " * 10


class KillsItself(FakeLLM):
    def __init__(self, signum):
        super().__init__()
        self.signum = signum

    def complete_json(self, **kwargs):
        os.kill(os.getpid(), self.signum)
        raise AssertionError("the signal must have stopped this call")


@pytest.mark.parametrize(
    ("signum", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)], ids=["SIGINT", "SIGTERM"]
)
def test_sb_run_exits_with_the_conventional_code_and_says_what_it_put_back(
    vault, config_file, monkeypatch, signum, code
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: KillsItself(signum))
    for n in (1, 2):
        (vault.root / "inbox" / f"Post{n}.md").write_text(CLIP.format(n=n))

    run = CliRunner().invoke(app, ["run", "--config", str(config_file)])

    assert run.exit_code == code
    assert "Interrupted: 1 item put back in the queue." in run.stderr
    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    assert queue.counts() == {"queued": 2}
    assert [i.attempts for i in queue.items("queued")] == [0, 0]


def test_sb_run_json_ends_with_a_finished_event_that_says_it_was_interrupted(
    vault, config_file, monkeypatch
):
    import json

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: KillsItself(signal.SIGINT))
    (vault.root / "inbox" / "Post1.md").write_text(CLIP.format(n=1))

    run = CliRunner().invoke(app, ["run", "--json", "--config", str(config_file)])

    events = [json.loads(line) for line in run.stdout.splitlines()]
    assert run.exit_code == 130
    assert events[-1]["event"] == "finished" and events[-1]["stopped_by"] == "interrupted"


def test_a_signal_waits_while_deferred_and_a_deferred_block_without_handlers_is_inert():
    with deferred():  # no handlers installed: nothing to wait for
        pass
    with pytest.raises(Interrupted):
        with handling(), interruptible():
            with deferred():
                os.kill(os.getpid(), signal.SIGTERM)
                reached_the_end = True  # the signal did not cut the block short
            pytest.fail("the signal must raise when the block ends")
    assert reached_the_end


def test_handler_state_is_fresh_for_each_use():
    with pytest.raises(Interrupted) as first:
        with handling(), interruptible():
            os.kill(os.getpid(), signal.SIGINT)
    assert first.value.signum == signal.SIGINT
    with handling():  # handler state is fresh for the next use
        os.kill(os.getpid(), signal.SIGTERM)  # protected: waits, nothing raised


class SlowOllama(BaseHTTPRequestHandler):
    """Reads the request, signals that a model call is in flight, and never answers in time."""

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.in_flight.set()
        self.server.release.wait(30)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize(
    ("signum", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)], ids=["SIGINT", "SIGTERM"]
)
def test_the_real_sb_run_is_interrupted_while_a_model_call_is_slow(vault, tmp_path, signum, code):
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowOllama)
    server.daemon_threads = True
    server.in_flight, server.release = threading.Event(), threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = tmp_path / "config.toml"
    config.write_text(
        f'[paths]\nvault = "{vault.root}"\n[notes]\nlanguage = "es"\n'
        f'[llm.summarize]\nmodel = "ollama/fake"\nbase_url = "http://127.0.0.1:{server.server_port}"\n'
    )
    for n in (1, 2):
        (vault.root / "inbox" / f"Post{n}.md").write_text(CLIP.format(n=n))
    env = {
        **os.environ,
        "ESBI_NO_UPDATE_CHECK": "1",
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "HOME": str(tmp_path),  # no real config, nothing of the maintainer's
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "esbi_cli.cli", "run", "--config", str(config)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert server.in_flight.wait(60), "the run never reached the model"
        proc.send_signal(signum)
        _, stderr = proc.communicate(timeout=20)  # prompt: the call is not waited for
    finally:
        server.release.set()
        proc.kill()
        server.shutdown()

    assert proc.returncode == code, stderr
    assert "Interrupted: 1 item put back in the queue." in stderr
    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    assert queue.counts() == {"queued": 2}
    assert [i.attempts for i in queue.items("queued")] == [0, 0]
    assert Queue(vault.root / ".esbi" / "queue.sqlite3").recover() == 0  # nothing left processing
