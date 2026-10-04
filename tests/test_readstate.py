from datetime import date

from conftest import add_source, write_daily

from esbi_cli.report.readstate import sync_read_state

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

    write_daily(vault, "2026-09-27", "- [ ] [[Nuevo]]\n")  # unticking does not revert
    sync_read_state(vault, today=date(2026, 10, 1))
    assert source(vault, "Nuevo").meta["status"] == "read"
