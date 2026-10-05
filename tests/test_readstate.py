from datetime import date

from conftest import add_source, write_daily

from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.report.readstate import sync_read_state, sync_unread_state

TODAY = date(2026, 9, 29)


def source(vault, title):
    return vault.read_page(vault.page_path("sources", title))


def test_a_ticked_checkbox_marks_the_source_read_on_the_day_the_tick_is_seen(vault):
    add_source(vault, "Artículo A")
    add_source(vault, "Artículo B")
    write_daily(
        vault,
        "2026-09-28",
        "## Procesado hoy\n- [x] [[Artículo A]] — resumen\n- [ ] [[Artículo B]] — resumen\n",
    )

    newly_read = sync_read_state(vault, today=TODAY)

    assert newly_read == ["Artículo A"]
    assert (
        source(vault, "Artículo A").meta["status"],
        source(vault, "Artículo A").meta["read"],
    ) == (
        "read",
        "2026-09-29",
    )
    assert (
        source(vault, "Artículo B").meta["status"],
        source(vault, "Artículo B").meta["read"],
    ) == (
        "processed",
        None,
    )


def test_ticks_are_one_way_idempotent_and_ignore_unknown_titles(vault):
    add_source(vault, "Ya leído", status="read", read="2026-09-20")
    add_source(vault, "Nuevo")
    write_daily(vault, "2026-09-25", "- [x] [[Ya leído]]\n- [ ] [[Nuevo]]\n- [x] [[No existe]]\n")
    write_daily(vault, "2026-09-27", "- [X] [[Nuevo|alias]]\n")

    assert sync_read_state(vault, today=TODAY) == ["Nuevo"]
    assert sync_read_state(vault, today=date(2026, 9, 30)) == []

    assert source(vault, "Ya leído").meta["read"] == "2026-09-20"
    assert source(vault, "Nuevo").meta["read"] == "2026-09-29"

    write_daily(vault, "2026-09-27", "- [ ] [[Nuevo]]\n")  # sync_read_state never reverts
    sync_read_state(vault, today=date(2026, 10, 1))
    assert source(vault, "Nuevo").meta["status"] == "read"


def test_unticking_a_source_in_the_note_of_its_day_puts_it_back_to_processed(vault):
    add_source(vault, "Artículo A", processed="2026-09-28", status="read", read="2026-09-29")
    add_source(vault, "Artículo B", processed="2026-09-28", status="read", read="2026-09-29")
    write_daily(
        vault,
        "2026-09-28",
        "## Procesado hoy\n- [ ] [[Artículo A]] — resumen\n- [x] [[Artículo B|alias]] — resumen\n",
    )

    assert sync_unread_state(vault) == ["Artículo A"]

    a, b = source(vault, "Artículo A"), source(vault, "Artículo B")
    assert (a.meta["status"], a.meta["read"]) == ("processed", None)
    assert (b.meta["status"], b.meta["read"]) == ("read", "2026-09-29")
    assert sync_unread_state(vault) == []  # idempotent


def test_a_source_that_does_not_appear_unticked_in_its_own_note_is_never_touched(vault):
    for title in ("Sin nota", "Sin caja", "Otra nota", "Es de hoy"):
        add_source(vault, title, processed="2026-09-28", status="read", read="2026-09-29")
    write_daily(vault, "2026-09-27", "- [ ] [[Otra nota]]\n")  # not the note of its day
    write_daily(vault, "2026-09-29", "- [ ] [[Es de hoy]]\n")  # not the note of its day either
    assert sync_unread_state(vault) == []  # "Sin nota": there is no note for 2026-09-28

    write_daily(vault, "2026-09-28", "## Procesado hoy\n- otra cosa sin caja\n")  # no checkbox
    assert sync_unread_state(vault) == []

    add_source(vault, "Sigue en proceso", processed="2026-09-28")  # not read: nothing to undo
    write_daily(vault, "2026-09-28", "- [ ] [[Sigue en proceso]]\n")
    assert sync_unread_state(vault) == []
    titles = ("Sin nota", "Sin caja", "Otra nota", "Es de hoy")
    assert {source(vault, t).meta["status"] for t in titles} == {"read"}


def test_a_box_that_is_ticked_anywhere_in_the_note_wins_over_an_unticked_duplicate(vault):
    add_source(vault, "Artículo A", processed="2026-09-28", status="read", read="2026-09-29")
    write_daily(vault, "2026-09-28", "- [ ] [[Artículo A]]\n- [x] [[Artículo A]]\n")

    assert sync_unread_state(vault) == []


def test_a_regenerated_note_shows_the_read_source_ticked_so_an_unticked_box_is_a_user_action(
    vault, queue
):
    add_source(vault, "Artículo A", processed=TODAY.isoformat())
    build_daily_index(vault, queue, TODAY)
    note = vault.wiki / "daily" / f"{TODAY.isoformat()}.md"
    ticked, unticked = "- [x] [[Artículo A]]", "- [ ] [[Artículo A]]"
    assert unticked in note.read_text(encoding="utf-8")

    note.write_text(note.read_text(encoding="utf-8").replace(unticked, ticked), encoding="utf-8")
    sync_read_state(vault, TODAY)
    build_daily_index(vault, queue, TODAY)  # the note is rewritten from state
    assert ticked in note.read_text(encoding="utf-8")
    assert sync_unread_state(vault) == []  # a regenerated, ticked box is not an untick
    assert source(vault, "Artículo A").meta["status"] == "read"

    note.write_text(note.read_text(encoding="utf-8").replace(ticked, unticked), encoding="utf-8")
    assert sync_unread_state(vault) == ["Artículo A"]
    build_daily_index(vault, queue, TODAY)
    assert unticked in note.read_text(encoding="utf-8")  # the view agrees
    assert sync_read_state(vault, TODAY) == []  # and it stays unticked: no flip-flop


def test_a_processed_value_that_is_not_a_date_never_points_at_another_file(vault):
    add_source(vault, "Artículo A", processed="../hostile", status="read", read="2026-09-29")
    (vault.wiki / "hostile.md").write_text("- [ ] [[Artículo A]]\n", encoding="utf-8")

    assert sync_unread_state(vault) == []

    assert source(vault, "Artículo A").meta["status"] == "read"
