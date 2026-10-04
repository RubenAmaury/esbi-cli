"""`sb eval`: how well does retrieval (and the answer) do on a set of questions with known sources."""

import json

from conftest import FakeLLM, add_source
from typer.testing import CliRunner

from esbi_cli import cli
from esbi_cli.cli import app
from esbi_cli.evaluate import evaluate, load_golden
from esbi_cli.vault import Page


def add_concept(vault, title, body):
    vault.write_page(
        Page(
            vault.page_path("concepts", title),
            {"type": "concept", "title": title, "summary": f"Resumen de {title}."},
            body,
        )
    )


def wiki(vault):
    add_source(
        vault,
        "Arnés de agentes extendido",
        body="# A\n\nEl arnés de código rodea al agente y orquesta herramientas.",
    )
    add_source(vault, "Cocina italiana", body="# C\n\nRecetas de pasta, salsas y pizza al horno.")
    add_source(
        vault,
        "Judge Model Paper",
        body="# J\n\nA judge model should accept when confident and escalate.",
    )


GOLDEN = [
    {"question": "¿Qué es el arnés de código del agente?", "expect": ["Arnés de agentes"]},
    {"question": "¿Cómo se hace la pasta?", "expect": ["Cocina"]},
    {"question": "¿Cuándo debe un juez aceptar y escalar?", "expect": ["Judge Model"]},
]


def write_golden(vault, rows=GOLDEN):
    path = vault.root / ".esbi" / "golden.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def test_the_golden_file_is_read_line_by_line_and_a_bad_line_says_which(vault):
    path = write_golden(vault)
    assert [g.question for g in load_golden(path)][0] == "¿Qué es el arnés de código del agente?"

    path.write_text('{"question": "ok", "expect": ["A"]}\nno es json\n', encoding="utf-8")
    try:
        load_golden(path)
    except ValueError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("a bad line must be refused")


def test_retrieval_is_scored_by_recall_and_reciprocal_rank_and_expectations_match_by_prefix(vault):
    wiki(vault)

    report = evaluate(vault, load_golden(write_golden(vault)), k=3)

    found = {c.question: c.rank for c in report.cases}
    assert found["¿Qué es el arnés de código del agente?"] == 1
    assert found["¿Cómo se hace la pasta?"] == 1
    assert (
        found["¿Cuándo debe un juez aceptar y escalar?"] is None
    )  # no word in common: Spanish vs English
    assert report.recall == 2 / 3 and abs(report.mrr - 2 / 3) < 1e-9


def test_rewriting_the_question_is_measured_as_an_option_and_recovers_the_cross_language_miss(
    vault,
):
    wiki(vault)
    llm = FakeLLM(
        {"terms": ["accept", "judge"]}, {"terms": []}, {"terms": []}
    )  # one rewrite per question, in order: the first question needs none, the third needs the terms
    golden = load_golden(write_golden(vault, [GOLDEN[2], GOLDEN[0], GOLDEN[1]]))

    report = evaluate(vault, golden, k=3, rewrite_llm=llm)

    assert [c.rank for c in report.cases] == [1, 1, 1] and report.recall == 1.0


def test_the_command_prints_the_numbers_and_the_misses_and_explains_a_missing_file(
    vault, config_file
):
    wiki(vault)
    missing = CliRunner().invoke(app, ["eval", "--config", str(config_file)])
    assert missing.exit_code == 1 and "golden.jsonl" in missing.output

    write_golden(vault)
    result = CliRunner().invoke(app, ["eval", "--config", str(config_file), "--k", "3"])

    assert result.exit_code == 0, result.output
    assert "recall@3" in result.stdout and "67%" in result.stdout and "MRR 0.67" in result.stdout
    assert "juez aceptar" in result.stdout  # the miss is listed so it can be looked at


def test_answers_can_be_scored_too_grounded_and_citing_the_expected_page(
    vault, config_file, monkeypatch
):
    wiki(vault)
    write_golden(vault, [GOLDEN[0]])
    answer = {
        "title": "Qué es el arnés",
        "one_liner": "Explicación breve del arnés.",
        "answer": "Rodea al agente ([[Arnés de agentes extendido]]).",
        "cited_pages": ["Arnés de agentes extendido"],
    }
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(answer))

    result = CliRunner().invoke(app, ["eval", "--config", str(config_file), "--answers"])

    assert result.exit_code == 0, result.output
    assert "grounded 100%" in result.stdout and "cites the expected page 100%" in result.stdout
