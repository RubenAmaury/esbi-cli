from conftest import add_source, make_plan

from esbi_cli.ask.answer import Answer
from esbi_cli.bench.metrics import answer_metrics, plan_metrics
from esbi_cli.llm.schemas import EditPlan


def plan(**overrides) -> EditPlan:
    return EditPlan.model_validate(make_plan(**overrides))


def test_a_plan_in_the_wikis_language_scores_clean(vault):
    metrics = plan_metrics(plan(), vault)

    assert metrics == {"concepts": 1, "entities": 1, "in_language": True, "bad_refs": 0}


def test_english_output_and_links_to_pages_that_do_not_exist_are_counted(vault):
    add_source(vault, "Fuente real")
    english = plan(
        one_liner="The paper describes how the model is trained with the data of the authors.",
        summary="This is a summary of the paper that is about the training of the model and the results.",
        related_pages=["Fuente real", "Inventada"],
        contradictions=[{"page": "Otra inventada", "note": "no existe esta página"}],
    )

    metrics = plan_metrics(english, vault)

    assert metrics["in_language"] is False
    assert metrics["bad_refs"] == 2  # "Inventada" and "Otra inventada"; "Fuente real" exists


def test_an_answer_is_scored_on_being_grounded_and_on_citing_the_page_it_should():
    good = Answer("¿Qué es X?", grounded=True, citations=["Otra", "X"])
    wrong_page = Answer("¿Qué es X?", grounded=True, citations=["Otra"])
    refused = Answer("¿Qué es X?", grounded=False)

    assert answer_metrics(good, expected="X") == {"grounded": True, "cites_expected": True}
    assert answer_metrics(wrong_page, expected="X") == {"grounded": True, "cites_expected": False}
    assert answer_metrics(refused, expected="X") == {"grounded": False, "cites_expected": False}
