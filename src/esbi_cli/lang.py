"""The languages the wiki can be written in: one catalogue, nothing else knows a language.

Code asks for text by language-independent key (`t("es", "summary")`) and recognises headings of
every catalogued language (`key_of`), so a vault written in one language and later switched to
another still reads. Adding a language is adding one entry to `LANGUAGES`: see
https://rubenamaury.github.io/esbi-cli/docs/how-to/add-a-language/.

Each entry has:
- `name`: how the prompts call the language ("Write all text in Spanish").
- `hint`: an optional extra line for the prompts, for a language a small model needs more help with.
- `stopwords`: common words used to notice an answer in the wrong language; empty skips the check.
- `generic_terms`: words too general to be a glossary entry ("data", "system"); they are dropped.
- `disclaimers`: a regex for a definition that says it has none ("not defined in the text").
- `relation_examples`: short labels for how two ideas relate, as the model should write them.
- `placeholders`: how a model that copied the prompt's wording starts a "summary" ("Executive summary of ...").
- `ask_example` / `rewrite_example`: worked outputs shown to the model, in this language.
- `labels`: every piece of text the program writes into the wiki.
"""

import re
import unicodedata
from collections.abc import Iterable

DEFAULT = "en"

LANGUAGES: dict[str, dict] = {
    "en": {
        "name": "English",
        "hint": "",
        "relation_examples": '"extends", "complements", "improves", "uses", "is an example of"',
        "stopwords": "the of and to in is that for with are this on as by from be an",
        "generic_terms": "data information system process technology example method approach result problem",
        "disclaimers": r"not (defined|mentioned|specified|provided|explained)|(does|do) not (define|mention|specify|explain|provide)|no definition",
        "placeholders": ("executive summary", "summary of"),
        "ask_example": (
            '{"title": "What is a graph", "one_liner": "A graph is a set of nodes joined by edges.", '
            '"answer": "A graph is a set of nodes connected by edges [[Graph]]. '
            'It is used to model networks [[Networks]].", "cited_pages": ["Graph", "Networks"]}'
        ),
        "rewrite_example": (
            'question "When should a judge accept and when escalate?" -> {"terms": ["judge", '
            '"accept", "escalate", "confidence", "confident", "threshold", "review"]}'
        ),
        "labels": {
            # sections of a source note
            "summary": "Executive summary",
            "abstract": "Detailed summary",
            "insights": "Key ideas",
            "key_points": "Key points",
            "terms": "Key terms",
            "quotes": "Key quotes",
            "diagram": "Diagram",
            "figures": "Figures",
            "connections": "Connections to your wiki",
            "open_questions": "Open questions",
            "concepts": "Concepts",
            "entities": "Entities",
            "related": "Related",
            "contradictions": "Possible contradictions",
            # elsewhere in notes
            "from_source": "From",
            "concept_summary": "Summary",
            "original_source": "Original source",
            "untitled": "Untitled",
            "source_suffix": "(source)",
            "figure": "Figure",
            "image": "Image",
            "no_subject": "No subject",
            "page_abbr": "p.",
            "contradiction_callout": "Possible contradiction ({date}) with {link}: {note}",
            "contradiction_review_name": "{date} contradiction - {source}",
            "contradiction_review_title": "Possible contradictions from {link}",
            "contradiction_review_footer": "Review and resolve; then delete this note.",
            "consolidate_review_name": "{page} - summary to review",
            "consolidate_review_title": "A summary proposed for {link} did not pass the checks",
            "consolidate_review_footer": "Nothing was changed. Check the proposal against the sections of the page; if it is right, paste it under the Summary heading and delete this note.",
            "merge_review_name": "{page} - possible merge",
            "merge_review_title": "Pages that may be the same idea as {link}",
            "merge_review_footer": "The worker never merges by itself. If they are the same idea, keep one page, add the other's name as an alias and delete the other; then delete this note.",
            # ask
            "no_answer": "I find nothing about this in the wiki.",
            "question_label": "Question",
            "sources": "Sources",
            "synthesis_suffix": "(synthesis)",
            "answer_title": "Answer",
            # index.md and log.md
            "index_title": "Index",
            "index_blurb": "Catalogue of the wiki ({total} pages). Kept by the worker.",
            "syntheses": "Syntheses",
            "log_created": "created: {names}",
            "log_updated": "updated: {names}",
            "log_review": "to review: {n}",
            # the daily index
            "daily_title": "Index of {date}",
            "daily_read": "Read",
            "daily_processed": "Processed today",
            "daily_queue": "Tomorrow's queue",
            "daily_review": "To review",
            "daily_revisit": "Revisit",
            "daily_runs": "Runs",
            "daily_stats": "Statistics",
            "nothing_read": "_Nothing new marked as read._",
            "nothing_processed": "_Nothing was processed today._",
            "queue_empty": "_The queue is empty._",
            "queue_one": "1 source in the queue",
            "queue_many": "{n} sources in the queue",
            "queue_cap": " (showing the {n} oldest)",
            "nothing_pending": "_Nothing pending._",
            "could_not_process": "- Could not process {name} ({error})",
            "retrying": "- Retrying {name} (attempt {n} of {max}): {error}",
            "llm_down_one": "- The model server was unreachable in the last run ({at}): 1 source is waiting. Start Ollama or check the model, then run `sb run`.",
            "llm_down_many": "- The model server was unreachable in the last run ({at}): {n} sources are waiting. Start Ollama or check the model, then run `sb run`.",
            "no_old_notes": "_No older notes to revisit yet._",
            "stat_pages": "- Pages: {total} (sources: {sources}, concepts: {concepts}, entities: {entities})",
            "stat_today": "- Today: {processed} sources processed, {touched} concepts/entities updated",
            "stat_read": "- Read: {read} of {total} sources",
            "stat_orphans": "- Orphans (no incoming links): {n}",
            "no_runs": "_No runs yet today._",
            "run_manual": " (manual)",
            "run_line": "- {at}{manual} — processed: {ingested}, skipped: {skipped}, failed: {failed} · {tokens} tokens · {duration}",
            "run_minutes": "{n} min",
            "run_under_minute": "<1 min",
            "run_stopped": " · stopped: {reason}",
            "stop_max_sources": "source limit",
            "stop_token_budget": "token budget",
            "stop_usd_budget": "USD budget",
            "stop_llm_unavailable": "model unavailable",
            "home_today": "- Today's index: {link}",
            "home_unread": "- Unread: {n} sources",
            "home_queue": "- Queued: {n} sources",
            # the lint report
            "lint_title": "Lint report ({date})",
            "lint_orphan": "Orphan pages",
            "lint_broken_link": "Broken links",
            "lint_missing_field": "Missing fields",
            "lint_unlinked_mention": "Unlinked mentions",
            "lint_near_duplicate": "Possible duplicates",
            "lint_missing_concept": "Concepts without a page",
            "lint_missing_field_line": "- [[{page}]]: missing `{field}`",
            "lint_unlinked_line": "- [[{page}]] mentions [[{target}]] without linking it",
            "lint_missing_concept_line": "- «{name}» appears in {sources} and has no page of its own",
            "lint_more": "… and {n} more",
            "lint_footer": "The worker only reports; nothing is fixed by itself. This report is regenerated on every run.",
            # the benchmark report
            "bench_title": "Model benchmark ({when})",
            "bench_header": "| model | success | no retry | median (s) | tokens/case | est. cost (USD) | {extra} |",
            "bench_extra_ingest": "right language / concepts",
            "bench_extra_ask": "cites the expected page",
            "bench_routing": "Routing recommendation",
            "bench_none": "no recommendation (no reliable model)",
            "bench_footer": "Only a suggestion: change `[llm.*]` in config.toml by hand if you agree.",
            "bench_question": "What is {title}?",
        },
    },
    "es": {
        "name": "Spanish",
        "hint": "",
        "relation_examples": '"amplía", "complementa", "mejora", "usa", "es un ejemplo de"',
        "stopwords": "de la el que en los las y un una para con por del se es al como más pero sus",
        "generic_terms": "datos información sistema proceso tecnología ejemplo método enfoque resultado problema",
        "disclaimers": r"no (se )?(define|menciona|especifica|explica|proporciona|detalla)|no (est[aá]|aparece) (definid|especificad|en el texto)|sin definici[oó]n",
        "placeholders": ("resumen ejecutivo", "resumen de"),
        "ask_example": (
            '{"title": "Qué es un grafo", "one_liner": "Un grafo es un conjunto de nodos unidos por aristas.", '
            '"answer": "Un grafo es un conjunto de nodos conectados por aristas [[Grafo]]. '
            'Se usa para modelar redes [[Redes]].", "cited_pages": ["Grafo", "Redes"]}'
        ),
        "rewrite_example": (
            'question "¿Cuándo debe un juez aceptar y cuándo escalar?" -> {"terms": ["juez", "judge", '
            '"aceptar", "accept", "escalar", "escalate", "confianza", "confident"]}'
        ),
        "labels": {
            "summary": "Resumen ejecutivo",
            "abstract": "Resumen detallado",
            "insights": "Ideas clave",
            "key_points": "Puntos clave",
            "terms": "Términos clave",
            "quotes": "Frases clave",
            "diagram": "Diagrama",
            "figures": "Figuras",
            "connections": "Conexiones con tu wiki",
            "open_questions": "Preguntas abiertas",
            "concepts": "Conceptos",
            "entities": "Entidades",
            "related": "Relacionado",
            "contradictions": "Posibles contradicciones",
            "from_source": "Desde",
            "concept_summary": "Resumen",
            "original_source": "Fuente original",
            "untitled": "Sin título",
            "source_suffix": "(fuente)",
            "figure": "Figura",
            "image": "Imagen",
            "no_subject": "Sin asunto",
            "page_abbr": "p.",
            "contradiction_callout": "Posible contradicción ({date}) con {link}: {note}",
            "contradiction_review_name": "{date} contradicción - {source}",
            "contradiction_review_title": "Posibles contradicciones desde {link}",
            "contradiction_review_footer": "Revisa y resuelve; luego borra esta nota.",
            "consolidate_review_name": "{page} - resumen por revisar",
            "consolidate_review_title": "Un resumen propuesto para {link} no pasó las comprobaciones",
            "consolidate_review_footer": "No se cambió nada. Compara la propuesta con las secciones de la página; si es correcta, pégala bajo el encabezado Resumen y borra esta nota.",
            "merge_review_name": "{page} - posible fusión",
            "merge_review_title": "Páginas que pueden ser la misma idea que {link}",
            "merge_review_footer": "El worker nunca fusiona por sí solo. Si son la misma idea, quédate con una página, añade el nombre de la otra como alias y borra la otra; luego borra esta nota.",
            "no_answer": "No encuentro nada sobre esto en la wiki.",
            "question_label": "Pregunta",
            "sources": "Fuentes",
            "synthesis_suffix": "(síntesis)",
            "answer_title": "Respuesta",
            "index_title": "Índice",
            "index_blurb": "Catálogo de la wiki ({total} páginas). Lo mantiene el worker.",
            "syntheses": "Síntesis",
            "log_created": "creadas: {names}",
            "log_updated": "actualizadas: {names}",
            "log_review": "por revisar: {n}",
            "daily_title": "Índice del {date}",
            "daily_read": "Leído",
            "daily_processed": "Procesado hoy",
            "daily_queue": "Cola de mañana",
            "daily_review": "Por revisar",
            "daily_revisit": "Repasar",
            "daily_runs": "Ejecuciones",
            "daily_stats": "Estadísticas",
            "nothing_read": "_Nada nuevo marcado como leído._",
            "nothing_processed": "_Hoy no se procesó nada._",
            "queue_empty": "_La cola está vacía._",
            "queue_one": "1 fuente en cola",
            "queue_many": "{n} fuentes en cola",
            "queue_cap": " (se muestran las {n} más antiguas)",
            "nothing_pending": "_Nada pendiente._",
            "could_not_process": "- No se pudo procesar {name} ({error})",
            "retrying": "- Reintentando {name} (intento {n} de {max}): {error}",
            "llm_down_one": "- El servidor del modelo no estaba disponible en la última ejecución ({at}): 1 fuente espera. Inicia Ollama o revisa el modelo y ejecuta `sb run`.",
            "llm_down_many": "- El servidor del modelo no estaba disponible en la última ejecución ({at}): {n} fuentes esperan. Inicia Ollama o revisa el modelo y ejecuta `sb run`.",
            "no_old_notes": "_Todavía no hay notas antiguas para repasar._",
            "stat_pages": "- Páginas: {total} (fuentes: {sources}, conceptos: {concepts}, entidades: {entities})",
            "stat_today": "- Hoy: {processed} fuentes procesadas, {touched} conceptos/entidades actualizados",
            "stat_read": "- Leídas: {read} de {total} fuentes",
            "stat_orphans": "- Huérfanas (sin enlaces entrantes): {n}",
            "no_runs": "_Todavía no hubo ejecuciones hoy._",
            "run_manual": " (manual)",
            "run_line": "- {at}{manual} — procesadas: {ingested}, omitidas: {skipped}, fallidas: {failed} · {tokens} tokens · {duration}",
            "run_minutes": "{n} min",
            "run_under_minute": "<1 min",
            "run_stopped": " · detenida: {reason}",
            "stop_max_sources": "límite de fuentes",
            "stop_token_budget": "presupuesto de tokens",
            "stop_usd_budget": "presupuesto en USD",
            "stop_llm_unavailable": "LLM no disponible",
            "home_today": "- Índice de hoy: {link}",
            "home_unread": "- Sin leer: {n} fuentes",
            "home_queue": "- En cola: {n} fuentes",
            "lint_title": "Informe de lint ({date})",
            "lint_orphan": "Páginas huérfanas",
            "lint_broken_link": "Enlaces rotos",
            "lint_missing_field": "Campos que faltan",
            "lint_unlinked_mention": "Menciones sin enlazar",
            "lint_near_duplicate": "Posibles duplicados",
            "lint_missing_concept": "Conceptos sin página",
            "lint_missing_field_line": "- [[{page}]]: falta `{field}`",
            "lint_unlinked_line": "- [[{page}]] menciona [[{target}]] sin enlazarlo",
            "lint_missing_concept_line": "- «{name}» aparece en {sources} y no tiene página propia",
            "lint_more": "… y {n} más",
            "lint_footer": "El worker solo informa; nada se corrige solo. Este informe se regenera en cada ejecución.",
            "bench_title": "Benchmark de modelos ({when})",
            "bench_header": "| modelo | éxito | sin reintento | mediana (s) | tokens/caso | coste est. (USD) | {extra} |",
            "bench_extra_ingest": "idioma correcto / conceptos",
            "bench_extra_ask": "cita la página esperada",
            "bench_routing": "Recomendación de enrutado",
            "bench_none": "sin recomendación (ningún modelo fiable)",
            "bench_footer": "Solo es una sugerencia: cambia `[llm.*]` en config.toml a mano si te convence.",
            "bench_question": "¿Qué es {title}?",
        },
    },
}


def supported() -> str:
    return ", ".join(LANGUAGES)


def get(code: str) -> dict:
    """The catalogue entry for `code`; a clear error naming the supported languages otherwise."""
    try:
        return LANGUAGES[code]
    except (KeyError, TypeError):
        raise ValueError(f"[notes].language must be one of: {supported()}, got {code!r}") from None


def name(code: str) -> str:
    return get(code)["name"]


def t(code: str, key: str, **values) -> str:
    """The text for `key` in language `code`, with `{placeholders}` filled in."""
    return get(code)["labels"][key].format(**values)


def _fold(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def every(key: str) -> list[str]:
    """The label for `key` in every language: what a reader must accept."""
    return list(dict.fromkeys(entry["labels"][key] for entry in LANGUAGES.values()))


def key_of(heading: str) -> str | None:
    """The key a heading belongs to, in whatever language it was written; None for any other."""
    wanted = _fold(heading)
    for entry in LANGUAGES.values():
        for key, label in entry["labels"].items():
            if _fold(label) == wanted:
                return key
    return None


def instruction(code: str) -> str:
    """The sentence every prompt carries to say which language to write in."""
    entry = get(code)
    return (
        f"Write ALL text in {entry['name']}, whatever language the source or the SCHEMA is in; "
        f"only verbatim quotes and term names keep the source's language. {entry['hint']}"
    ).strip()


def _hits(text: str, code: str) -> int:
    words = set(LANGUAGES[code]["stopwords"].split())
    return sum(w in words for w in re.findall(r"[^\W\d_]+", text.lower()))


def wrong_language(text: str, code: str, min_hits: int = 4) -> bool:
    """Is `text` clearly in another catalogued language than `code`? A cheap stopword count: small
    models often answer in the source's language. A language with no stopwords is never judged.
    `min_hits` is how many stopwords it takes; a one-sentence definition needs fewer."""
    if not get(code)["stopwords"]:
        return False
    own = _hits(text, code)
    return any(
        _hits(text, other) >= min_hits and _hits(text, other) > 1.5 * own
        for other, entry in LANGUAGES.items()
        if other != code and entry["stopwords"]
    )


SHORT_FIELD_CHARS = 300  # under this, a field is a sentence or two: fewer stopwords are enough


def leaking(fields: Iterable[tuple[str, str]], code: str) -> list[str]:
    """The names of the (name, text) fields written in another catalogued language than `code`,
    each field judged on its own: joined with a long field in the right language, a short one in
    the wrong language goes unnoticed. A language without a word list is never judged."""
    return list(
        dict.fromkeys(
            name
            for name, text in fields
            if wrong_language(text, code, 4 if len(text) >= SHORT_FIELD_CHARS else 2)
        )
    )
