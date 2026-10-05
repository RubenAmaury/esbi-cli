"""Email never reaches a model that sends text off the machine."""

import pytest
from conftest import FakeLLM, add_source, make_plan

from esbi_cli.ask.answer import answer_question
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.privacy import PrivacyError
from esbi_cli.vault import Page

SECRET = "El contrato con Acme vence en marzo y nadie debe saberlo."


def cloud(*payloads):
    llm = FakeLLM(*payloads)
    llm.sends_text_out = True
    return llm


def email_doc():
    return ExtractedDoc("Asunto privado", (SECRET + " ") * 30, "email", "mail:abc@x.test")


def article_doc():
    return ExtractedDoc(
        "Un artículo público",
        "Los agentes de IA usan un arnés de código; el contrato Acme se discute aparte. " * 30,
        "article",
        "https://x.test/a",
    )


def run(vault, cfg, doc, llm, **kw):
    return ingest("x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: doc, **kw)


def seed_email_wiki(vault):
    """An email-derived source, a concept only it created, and one shared with a public source."""
    add_source(vault, "Asunto privado", body="# S\n\n" + SECRET)
    private = vault.read_page(vault.page_path("sources", "Asunto privado"))
    private.meta["kind"] = "email"
    vault.write_page(private)
    add_source(vault, "Fuente pública", body="# P\n\nSobre agentes.")
    for title, sources, body in [
        ("Contrato Acme", ["[[Asunto privado]]"], f"# C\n\n## Desde [[Asunto privado]]\n{SECRET}"),
        (
            "Arnés de agente",
            ["[[Asunto privado]]", "[[Fuente pública]]"],
            f"# A\n\n## Desde [[Fuente pública]]\nCapa de código del agente.\n\n## Desde [[Asunto privado]]\n{SECRET}",
        ),
    ]:
        vault.write_page(
            Page(
                vault.page_path("concepts", title),
                {
                    "type": "concept",
                    "title": title,
                    "sources": sources,
                    "summary": f"Resumen de {title}.",
                },
                body,
            )
        )


def test_an_email_is_written_by_the_private_model_and_the_cloud_model_never_sees_it(vault, cfg):
    writer, private = cloud(), FakeLLM(make_plan(title="Asunto privado"))

    result = run(vault, cfg, email_doc(), writer, private_llm=private)

    assert result.status == "ingested" and writer.calls == [] and len(private.calls) == 1


def test_an_email_with_a_cloud_writer_and_no_private_model_is_refused_before_any_call(vault, cfg):
    writer = cloud(make_plan())

    with pytest.raises(PrivacyError, match=r"\[llm.private\]"):
        run(vault, cfg, email_doc(), writer)

    assert writer.calls == []


def test_a_cloud_model_writing_a_public_source_is_not_told_about_email_pages(vault, cfg):
    seed_email_wiki(vault)
    writer = cloud(make_plan(title="Un artículo público"))

    run(vault, cfg, article_doc(), writer)

    prompt = writer.calls[0]["user"]
    assert "Asunto privado" not in prompt and "Contrato Acme [concepts]" not in prompt
    assert "Arnés de agente" in prompt  # shared with a public source: still a candidate


def test_a_local_model_still_sees_everything(vault, cfg):
    seed_email_wiki(vault)
    local = FakeLLM(make_plan(title="Un artículo público"))

    run(vault, cfg, article_doc(), local)

    assert "Contrato Acme [concepts]" in local.calls[0]["user"]


def test_ask_with_a_cloud_model_sends_no_email_text_not_even_from_shared_pages(vault):
    seed_email_wiki(vault)
    answer = {
        "title": "Qué es un arnés",
        "one_liner": "Explicación breve del arnés.",
        "answer": "El arnés es la capa de código ([[Arnés de agente]]).",
        "cited_pages": ["Arnés de agente"],
    }
    llm = cloud(answer)

    answer_question(vault, llm, "¿Qué es el arnés de agente y el contrato Acme?")

    prompt = llm.calls[0]["user"]
    assert SECRET not in prompt and "vence en marzo" not in prompt
    assert "Capa de código del agente." in prompt  # the public part of the shared page stays


# ---- gaps found by the pre-publication audit -------------------------------------------------


def test_the_benchmark_neither_uses_email_as_a_case_nor_hides_that_its_model_is_a_cloud_one(vault):
    from esbi_cli.bench.cases import load_cases
    from esbi_cli.bench.runner import _CountingLLM

    (vault.root / "raw").mkdir(exist_ok=True)
    (vault.root / "raw" / "2026-10-01-correo.md").write_text(
        f"---\ntitle: Correo\nkind: email\n---\n{SECRET * 20}", encoding="utf-8"
    )
    (vault.root / "raw" / "2026-10-01-articulo.md").write_text(
        f"---\ntitle: Artículo\nkind: article\n---\n{'Texto público largo. ' * 60}",
        encoding="utf-8",
    )
    seed_email_wiki(vault)

    ingest_cases, ask_cases = load_cases(vault, 10)

    assert [c.name for c in ingest_cases] == [
        "2026-10-01-articulo"
    ]  # the email snapshot is not a case
    assert "Contrato Acme" not in [
        c.expected for c in ask_cases
    ]  # nor a concept built only from email
    assert _CountingLLM(cloud()).sends_text_out is True


def test_a_pdf_that_arrived_as_a_mail_attachment_is_email_to_the_privacy_rules(vault, cfg):
    from test_mail_convert import raw_email

    from esbi_cli.mail.fetch import fetch_mail

    pdf = b"%PDF-1.4 contenido del adjunto"
    fetch_mail(
        FakeMailClientOne(raw_email(msgid="<a@x.test>", attachments=[("Contrato.pdf", pdf)])), vault
    )
    paper = ExtractedDoc("Contrato", (SECRET + " ") * 30, "paper", None, pdf_bytes=pdf)

    with pytest.raises(PrivacyError):  # a cloud writer and no [llm.private]
        run(vault, cfg, paper, cloud(make_plan()))

    private = FakeLLM(make_plan(title="Contrato"))
    writer = cloud()
    result = run(vault, cfg, paper, writer, private_llm=private)
    assert writer.calls == [] and len(private.calls) == 1
    assert vault.read_page(result.applied.source_path).meta["kind"] == "email"


def FakeMailClientOne(raw):
    from conftest import FakeMailClient

    return FakeMailClient(("1", raw))


def test_a_local_model_with_a_cloud_fallback_counts_as_sending_text_out():
    from esbi_cli.config import LLMConfig
    from esbi_cli.llm.adapter import make_llm

    both = make_llm(LLMConfig(model="ollama/m", fallback="openai/gpt-x"))
    assert both.sends_text_out is True  # when the local model fails the text goes to the fallback
    assert make_llm(LLMConfig(model="ollama/m", fallback="ollama/n")).sends_text_out is False


@pytest.mark.parametrize(
    "model, base_url, sends",
    [
        ("ollama/llama3.2", None, False),
        ("ollama/llama3.2", "http://127.0.0.1:11434", False),
        ("ollama/llama3.2", "http://gpu.example.test:11434", True),  # another machine
        ("ollama/gpt-oss:120b-cloud", None, True),  # Ollama's hosted models run elsewhere
        ("lmstudio/m", None, False),
        ("lmstudio/m", "http://192.168.1.5:1234/v1", True),
    ],
)
def test_a_local_runtime_pointed_at_another_machine_or_a_hosted_model_is_not_local(
    model, base_url, sends
):
    from esbi_cli.config import LLMConfig
    from esbi_cli.llm.adapter import make_llm

    assert make_llm(LLMConfig(model=model, base_url=base_url)).sends_text_out is sends


def test_the_private_model_must_itself_run_on_this_machine(vault, cfg):
    with pytest.raises(PrivacyError, match="private"):
        run(vault, cfg, email_doc(), cloud(), private_llm=cloud(make_plan()))


def test_a_synthesis_that_used_any_email_page_is_hidden_from_a_cloud_ask(vault):
    seed_email_wiki(vault)
    vault.write_page(
        Page(
            vault.page_path("syntheses", "Qué dice el contrato"),
            {
                "type": "synthesis",
                "title": "Qué dice el contrato",
                "sources": ["[[Asunto privado]]", "[[Fuente pública]]"],
                "summary": "Resumen del contrato.",
            },
            f"# Qué dice el contrato\n\n{SECRET}",
        )
    )
    answer = {
        "title": "Contrato",
        "one_liner": "Sobre el contrato de Acme.",
        "answer": "Hay un contrato ([[Fuente pública]]).",
        "cited_pages": ["Fuente pública"],
    }
    llm = cloud(answer)

    answer_question(vault, llm, "¿Qué dice el contrato de Acme?")

    assert SECRET not in llm.calls[0]["user"]


def test_a_page_born_from_email_loses_its_email_summary_when_a_public_source_joins_it(vault, cfg):
    private_plan = make_plan(
        title="Asunto privado",
        concepts=[{"title": "Contrato", "aliases": [], "description": SECRET}],
        entities=[],
    )
    run(vault, cfg, email_doc(), FakeLLM(private_plan), private_llm=None)
    public_plan = make_plan(
        title="Un artículo público",
        concepts=[
            {"title": "Contrato", "aliases": [], "description": "Un contrato es un acuerdo."}
        ],
        entities=[],
    )

    run(vault, cfg, article_doc(), FakeLLM(public_plan))

    page = vault.read_page(vault.page_path("concepts", "Contrato"))
    assert SECRET not in page.meta["summary"]  # it would be sent out as a one-line description


def test_a_cloud_model_connecting_a_note_is_shown_no_summary_of_a_page_email_helped_write(
    vault, cfg
):
    from dataclasses import replace

    seed_email_wiki(vault)
    shared = vault.read_page(vault.page_path("concepts", "Arnés de agente"))
    shared.meta["summary"] = f"Resumen con {SECRET}"
    vault.write_page(shared)
    cfg = replace(cfg, find_connections=True)
    writer = cloud(make_plan(title="Un artículo público"), {"connections": []})

    run(vault, cfg, article_doc(), writer)

    assert SECRET not in writer.calls[1]["user"]  # the connection call
    assert "Arnés de agente" in writer.calls[1]["user"]  # the page is still offered, by title


def test_a_public_note_is_never_connected_to_email_even_by_a_local_model(vault, cfg):
    from dataclasses import replace

    seed_email_wiki(vault)
    cfg = replace(cfg, find_connections=True)
    concept = {"title": "Acuerdo", "aliases": [], "description": "Sobre el contrato Acme."}
    local = FakeLLM(
        make_plan(
            title="Un artículo público",
            concepts=[concept],
            summary="Habla del contrato Acme y su vencimiento en marzo.",
        ),
        {"connections": []},
    )

    run(vault, cfg, article_doc(), local)

    offered = local.calls[1]["user"].split("<existing_pages>")[1]
    assert "Asunto privado" not in offered and "Contrato Acme" not in offered


def test_an_image_that_arrived_as_a_mail_attachment_is_email_to_the_privacy_rules(vault, cfg):
    from test_mail_convert import picture, raw_email

    from esbi_cli.mail.fetch import fetch_mail

    png = picture()
    fetch_mail(
        FakeMailClientOne(
            raw_email(msgid="<a@x.test>", images=[("Captura.png", png, "image/png")])
        ),
        vault,
    )
    shot = ExtractedDoc("Captura", (SECRET + " ") * 30, "article", None, image_bytes=png)

    with pytest.raises(PrivacyError):  # a cloud writer and no [llm.private]
        run(vault, cfg, shot, cloud(make_plan()))

    private, writer = FakeLLM(make_plan(title="Captura")), cloud()
    result = run(vault, cfg, shot, writer, private_llm=private)
    assert writer.calls == [] and len(private.calls) == 1
    assert vault.read_page(result.applied.source_path).meta["kind"] == "email"


def test_an_image_that_was_not_in_a_mail_stays_public(vault, cfg):
    from test_mail_convert import picture

    shot = ExtractedDoc("Captura", (SECRET + " ") * 30, "article", None, image_bytes=picture())
    writer = cloud(make_plan(title="Captura"))

    run(vault, cfg, shot, writer)

    assert len(writer.calls) == 1


def web_page_doc():
    return ExtractedDoc(
        "Una página enlazada",
        "La página enlazada habla de agentes y de su arnés de código. " * 30,
        "article",
        "https://blog.test/uno",
    )


def test_a_page_linked_from_a_mail_is_never_sent_to_a_cloud_model(vault, cfg):
    writer, private = (
        cloud(make_plan(title="Una página enlazada")),
        FakeLLM(make_plan(title="Una página enlazada")),
    )

    result = run(vault, cfg, web_page_doc(), writer, private_llm=private, from_email=True)

    assert writer.calls == [] and len(private.calls) == 1
    assert vault.read_page(result.applied.source_path).meta["kind"] == "email"


def test_a_page_linked_from_a_mail_is_refused_when_only_a_cloud_model_is_configured(vault, cfg):
    writer = cloud(make_plan())

    with pytest.raises(PrivacyError, match=r"\[llm.private\]"):
        run(vault, cfg, web_page_doc(), writer, from_email=True)

    assert writer.calls == []


def test_the_note_made_from_a_mail_link_counts_as_email_for_every_filter(vault, cfg):
    from esbi_cli.privacy import email_touched, private_titles

    private = FakeLLM(make_plan(title="Una página enlazada"))
    run(vault, cfg, web_page_doc(), cloud(), private_llm=private, from_email=True)

    assert "Una página enlazada" in private_titles(vault)
    assert email_touched(vault)  # its concepts are email-touched: a cloud model gets titles only
    later = cloud(make_plan(title="Un artículo público"))
    run(vault, cfg, article_doc(), later)
    assert "Una página enlazada" not in later.calls[0]["user"]
