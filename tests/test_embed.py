"""Hybrid retrieval: a dense (embedding) side next to FTS5, fused by reciprocal rank."""

import httpx
import pytest
from conftest import FakeEmbedder, FakeLLM, make_plan
from test_privacy import SECRET, seed_email_wiki

from esbi_cli.config import Config, LLMConfig
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.ingest.retrieve import find_candidates
from esbi_cli.llm import adapter
from esbi_cli.llm.adapter import LLMError, make_embedder
from esbi_cli.vault import Page, Vault


def add_concept(vault, title, body):
    fields = {"type": "concept", "title": title, "summary": f"Resumen de {title}."}
    vault.write_page(Page(vault.page_path("concepts", title), fields, body))


def titles(vault, text, **kw):
    return [c.title for c in find_candidates(vault, text, **kw)]


def seed_pets(vault):
    add_concept(vault, "Felinos", "# Felinos\n\nLos felinos domésticos duermen mucho.")
    add_concept(vault, "Cocina", "# Cocina\n\nRecetas de pasta y salsas.")


# ---- the point of it: meaning without shared words ----------------------------------------------


def test_a_question_that_shares_no_word_with_a_note_still_finds_it(vault):
    seed_pets(vault)
    question = "my cat sleeps all day"  # no word in common with the note: FTS5 finds nothing

    assert titles(Vault(vault.root), question) == []  # today's behaviour, no embedder
    # the nearest page by meaning comes first; the dense side always returns its nearest pages
    assert titles(Vault(vault.root, embedder=FakeEmbedder()), question)[0] == "Felinos"


def test_a_keyword_hit_and_a_meaning_hit_are_both_returned(vault):
    add_concept(vault, "Felinos", "# F\n\nEl gato duerme. Cat nap.")
    add_concept(vault, "Siesta", "# S\n\nLa siesta del mediodía es sagrada.")
    add_concept(vault, "Coches", "# C\n\nUn coche necesita revisión.")
    hybrid = Vault(vault.root, embedder=FakeEmbedder())

    # "siesta" matches Siesta by keyword only; "cat" matches Felinos by meaning only
    assert set(titles(hybrid, "siesta cat")[:2]) == {"Siesta", "Felinos"}


def test_without_an_embedder_search_is_exactly_what_it_was(vault):
    seed_pets(vault)
    assert titles(Vault(vault.root), "felinos domésticos") == ["Felinos"]


# ---- never break a run ------------------------------------------------------------------------


def test_a_failing_embedder_falls_back_to_keywords_and_says_so_once(vault, capsys):
    seed_pets(vault)
    down = Vault(
        vault.root, embedder=FakeEmbedder(fail=LLMError("http://localhost:11434 unreachable"))
    )

    assert titles(down, "felinos domésticos") == ["Felinos"]
    assert titles(down, "felinos duermen") == ["Felinos"]

    err = capsys.readouterr().err
    assert err.count("embeddings unavailable") == 1 and "keyword" in err


# ---- store: only what changed is embedded ------------------------------------------------------


def test_only_new_or_changed_pages_are_embedded_again(vault):
    seed_pets(vault)
    embedder = FakeEmbedder()
    titles(Vault(vault.root, embedder=embedder), "my cat")
    assert len(embedder.seen) == 2 and len(embedder.queries) == 1

    embedder.seen.clear()
    titles(Vault(vault.root, embedder=embedder), "my cat")  # a new process, nothing changed
    assert embedder.seen == []

    add_concept(vault, "Felinos", "# Felinos\n\nAhora también hablan del gato salvaje.")
    titles(Vault(vault.root, embedder=embedder), "my cat")
    assert len(embedder.seen) == 1 and "salvaje" in embedder.seen[0]


def test_a_page_is_embedded_by_section_each_with_its_title(vault):
    add_concept(vault, "Mezcla", "# Mezcla\n\nIntro.\n\n## Gatos\nEl gato.\n\n## Panes\nEl pan.")
    embedder = FakeEmbedder()

    titles(Vault(vault.root, embedder=embedder), "cat")

    assert len(embedder.seen) == 3 and all("Mezcla" in t for t in embedder.seen)
    assert any("El gato." in t and "El pan." not in t for t in embedder.seen)


def test_a_different_embedding_model_means_every_page_is_embedded_again(vault):
    seed_pets(vault)
    embedder = FakeEmbedder()
    titles(Vault(vault.root, embedder=embedder), "my cat")

    embedder.identity, embedder.seen = "fake/another-model", []
    titles(Vault(vault.root, embedder=embedder), "my cat")

    assert any("domésticos" in t for t in embedder.seen)  # vectors from another model are useless


def test_a_deleted_page_leaves_no_vector_behind(vault):
    seed_pets(vault)
    assert titles(Vault(vault.root, embedder=FakeEmbedder()), "my cat")[0] == "Felinos"

    vault.page_path("concepts", "Felinos").unlink()

    assert titles(Vault(vault.root, embedder=FakeEmbedder()), "my cat") == ["Cocina"]


# ---- privacy: email never goes to an embedder that sends text out -----------------------------


def test_a_remote_embedder_is_never_given_email_nor_what_email_added_to_shared_pages(vault):
    seed_email_wiki(vault)
    remote = FakeEmbedder(sends_text_out=True)

    titles(Vault(vault.root, embedder=remote), "contrato agentes")

    assert remote.seen and not any(SECRET in t or "Asunto privado" in t for t in remote.seen)
    assert any("Capa de código del agente." in t for t in remote.seen)  # the public part goes


def test_a_local_embedder_may_read_everything(vault):
    seed_email_wiki(vault)
    local = FakeEmbedder()

    titles(Vault(vault.root, embedder=local), "contrato agentes")

    assert any(SECRET in t for t in local.seen)


def test_the_text_of_an_email_is_not_sent_as_a_query_to_a_remote_embedder(vault):
    seed_pets(vault)
    remote = FakeEmbedder(sends_text_out=True)

    found = titles(Vault(vault.root, embedder=remote), "felinos domésticos", private=True)

    assert found == ["Felinos"]  # keywords still work
    assert remote.queries == []


def test_ingesting_an_email_never_sends_its_text_to_a_remote_embedder(vault):
    seed_pets(vault)
    remote = FakeEmbedder(sends_text_out=True)
    hybrid = Vault(vault.root, embedder=remote, language="es")
    cfg = Config(vault=vault.root, language="es", max_source_chars=5000, find_connections=True)
    mail = ExtractedDoc("Asunto privado", (SECRET + " ") * 30, "email", "mail:abc@x.test")
    connections = {"connections": []}  # the connect call's answer: none, the query is the point
    local = FakeLLM(make_plan(title="Asunto privado"), connections)

    ingest("x", vault=hybrid, llm=local, cfg=cfg, extractor=lambda _: mail, private_llm=local)

    assert remote.queries == []


# ---- the provider layer -------------------------------------------------------------------------


def fake_post(response, seen):
    def post(url, headers, json, timeout):  # noqa: A002 - mirrors httpx.post
        seen.append({"url": url, "json": json})
        return httpx.Response(200, json=response, request=httpx.Request("POST", url))

    return post


def test_ollama_embeds_a_batch_with_the_nomic_prefixes(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"embeddings": [[1, 0], [0, 1]]}, seen))
    embedder = make_embedder(LLMConfig(model="ollama/nomic-embed-text"))

    assert embedder.embed(["uno", "dos"]) == [[1, 0], [0, 1]]
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"embeddings": [[1]]}, seen))
    embedder.embed(["¿qué?"], query=True)

    assert seen[0]["url"] == "http://localhost:11434/api/embed"
    assert seen[0]["json"]["model"] == "nomic-embed-text"
    assert seen[0]["json"]["input"] == ["search_document: uno", "search_document: dos"]
    assert seen[1]["json"]["input"] == ["search_query: ¿qué?"]
    assert embedder.sends_text_out is False


def test_an_embedding_model_without_prefixes_gets_the_text_as_it_is(monkeypatch):
    seen: list = []
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"embeddings": [[1]]}, seen))
    make_embedder(LLMConfig(model="ollama/bge-m3")).embed(["uno"])
    assert seen[0]["json"]["input"] == ["uno"]


def test_an_embedder_on_another_machine_sends_text_out():
    cfg = LLMConfig(model="ollama/nomic-embed-text", base_url="http://gpu.test:11434")
    assert make_embedder(cfg).sends_text_out is True


def test_only_ollama_embeds_for_now_and_the_error_says_so():
    with pytest.raises(ValueError, match="ollama"):
        make_embedder(LLMConfig(model="openai/text-embedding-3-small"))


def test_a_server_that_returns_the_wrong_number_of_vectors_is_an_error(monkeypatch):
    monkeypatch.setattr(adapter.httpx, "post", fake_post({"embeddings": [[1]]}, []))
    with pytest.raises(LLMError):
        make_embedder(LLMConfig(model="ollama/m")).embed(["a", "b"])
