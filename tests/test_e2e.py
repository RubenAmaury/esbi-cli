"""End to end: one user's first day, through the real CLI. Only what lies outside the process is
faked: the model (at `cli.make_llm`) and the web (a real HTTP server on 127.0.0.1, reached through
the real `netguard.safe_get` with its resolver and client seams, as test_update does)."""

import subprocess
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from conftest import FakeLLM, make_plan
from pdf_fixtures import pdf_bytes
from test_ask import plan as answer_plan
from typer.testing import CliRunner

from esbi_cli import cli, extract, netguard
from esbi_cli.cli import app

ARTICLE = (
    "<html><head><title>Memoria de agentes</title></head><body><article>"
    "<h1>Memoria de agentes</h1>"
    + "".join(
        f"<p>Nota {i}: los agentes de IA usan un arnés de código para planificar y ejecutar "
        "herramientas. El arnés gestiona el contexto, la memoria y la verificación.</p>"
        for i in range(6)
    )
    + "</article></body></html>"
).encode()


class Article(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(ARTICLE)))
        self.end_headers()
        self.wfile.write(ARTICLE)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_web(monkeypatch):
    """A web page on 127.0.0.1, fetched through the real safe_get: the name resolves to a public
    address (so the guard passes) and the client's transport delivers the pinned request here."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Article)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port

    class ToLocalServer(httpx.HTTPTransport):
        def handle_request(self, request):
            request.url = request.url.copy_with(host="127.0.0.1", port=port)
            return super().handle_request(request)

    def public(host, port, *args, **kwargs):  # a global address: never contacted, see above
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    real_safe_get = netguard.safe_get

    def safe_get(url, **kwargs):
        # safe_get only applies `headers` to a client it builds itself, so this one carries them
        client = httpx.Client(
            transport=ToLocalServer(), headers=kwargs.get("headers"), trust_env=False
        )
        with client:
            return real_safe_get(url, client=client, resolver=public, **kwargs)

    monkeypatch.setattr(extract, "safe_get", safe_get)
    yield f"http://web.example:{port}/memoria"
    server.shutdown()
    server.server_close()


def git(vault, *args):
    return subprocess.run(
        ["git", *args], cwd=vault, capture_output=True, text=True, check=True
    ).stdout


def test_a_user_adds_a_pdf_and_a_link_runs_and_asks(tmp_path, monkeypatch, local_web):
    vault, config = tmp_path / "Brain", tmp_path / "cfg" / "config.toml"
    pdf = tmp_path / "Arnés de agentes.pdf"
    pdf.write_bytes(pdf_bytes("plain-text.pdf"))
    runner = CliRunner()

    def sb(*args):
        result = runner.invoke(app, [*args, "--config", str(config)])
        assert result.exit_code == 0, result.output
        return result.stdout

    init = runner.invoke(
        app,
        ["init", "--vault", str(vault), "--config-file", str(config), "--language", "es",
         "--no-obsidian", "--nightly", "none", "--no-ocr"],
    )  # fmt: skip
    assert init.exit_code == 0, init.output

    assert "Queued 2" in sb("add", str(pdf), local_web)

    connection = {
        "page": "Arnés de agentes",
        "relation": "amplía",
        "why": "Las dos explican cómo un arnés de código guía a un agente.",
    }
    run_llm = FakeLLM(
        make_plan(),  # the PDF, queued first
        make_plan(title="Memoria de agentes", entities=[]),  # the link
        {"connections": [connection]},  # the link relates to the PDF's note
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: run_llm)
    run = sb("run")

    assert "ingested: 2" in run and "failed: 0" in run, run
    sources = vault / "wiki" / "sources"
    assert sorted(p.name for p in sources.glob("*.md")) == [
        "Arnés de agentes.md",
        "Memoria de agentes.md",
    ]
    link_note = (sources / "Memoria de agentes.md").read_text(encoding="utf-8")
    assert local_web in link_note and "[[Arnés de agentes]]" in link_note
    daily = vault / "wiki" / "daily" / f"{date.today().isoformat()}.md"
    daily_text = daily.read_text(encoding="utf-8")
    assert "[[Arnés de agentes]]" in daily_text and "[[Memoria de agentes]]" in daily_text
    log = git(vault, "log", "--format=%s")
    assert "ingest: Arnés de agentes" in log and "ingest: Memoria de agentes" in log
    assert git(vault, "status", "--porcelain") == ""  # the whole batch is committed

    status = sb("status")
    assert "done: 2" in status and "queued: 0" in status and "failed: 0" in status

    ask_llm = FakeLLM(answer_plan(cited_pages=["Arnés de agente", "Arnés de agentes"]))
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: ask_llm)
    answer = sb("ask", "¿Qué es un arnés de agente?")

    assert "Sources: [[Arnés de agente]], [[Arnés de agentes]]" in answer
    assert "arnés de código" in ask_llm.calls[0]["user"]  # it read the ingested pages
    assert run_llm.payloads == [] and ask_llm.payloads == []  # every faked answer was used
