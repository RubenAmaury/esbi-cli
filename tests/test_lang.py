import re

import pytest

from esbi_cli import lang


def test_the_default_language_is_english():
    assert lang.DEFAULT == "en"


def test_every_language_has_every_label_english_has_with_the_same_placeholders():
    english = lang.LANGUAGES["en"]
    for code, entry in lang.LANGUAGES.items():
        assert set(entry) == set(english), code
        assert set(entry["labels"]) == set(english["labels"]), code
        for key, text in entry["labels"].items():
            assert set(re.findall(r"{(\w+)}", text)) == set(
                re.findall(r"{(\w+)}", english["labels"][key])
            ), f"{code}.{key}"


def test_an_unsupported_language_is_refused_with_the_supported_ones_listed():
    with pytest.raises(ValueError, match=r"must be one of: en, es"):
        lang.get("fr")


def test_a_label_is_looked_up_by_language_independent_key():
    assert lang.t("en", "summary") == "Executive summary"
    assert lang.t("es", "summary") == "Resumen ejecutivo"
    assert lang.t("es", "daily_title", date="2026-10-03") == "Índice del 2026-10-03"


def test_every_heading_a_reader_may_find_maps_back_to_its_key_in_any_language():
    assert lang.key_of("Executive summary") == "summary"
    assert lang.key_of("Resumen ejecutivo") == "summary"
    assert lang.key_of("  términos CLAVE ") == "terms"  # case, accents and spaces do not matter
    assert lang.key_of("Something else") is None
    assert {lang.t(code, "from_source") for code in lang.LANGUAGES} == set(
        lang.every("from_source")
    )


def test_the_wrong_language_is_detected_in_both_directions():
    english = "The model is used for this task and the results are good for the users in that case."
    spanish = "El modelo se usa para esta tarea y los resultados son buenos para los usuarios en ese caso."
    assert lang.wrong_language(english, "es")
    assert not lang.wrong_language(spanish, "es")
    assert lang.wrong_language(spanish, "en")
    assert not lang.wrong_language(english, "en")


def test_a_language_without_stopwords_is_never_guessed(monkeypatch):
    monkeypatch.setitem(lang.LANGUAGES, "xx", {**lang.LANGUAGES["en"], "stopwords": ""})
    assert not lang.wrong_language("El modelo se usa para esta tarea y los resultados.", "xx")


def test_a_language_is_added_with_data_only(monkeypatch):
    klingon = {**lang.LANGUAGES["en"], "name": "Klingon", "stopwords": ""}
    klingon["labels"] = {**klingon["labels"], "summary": "Qaw"}
    monkeypatch.setitem(lang.LANGUAGES, "tlh", klingon)
    assert lang.get("tlh")["name"] == "Klingon"
    assert lang.t("tlh", "summary") == "Qaw"
    assert lang.key_of("Qaw") == "summary"
    assert "tlh" in str(pytest.raises(ValueError, lang.get, "fr").value)
