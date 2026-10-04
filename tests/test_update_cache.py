"""The update cache: the network is asked at most once a day."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from esbi_cli.update import CHECK_INTERVAL_SECONDS, Release, cache_dir, cached_latest

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
V2 = Release("0.2.0", "https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.2.0")


class Asker:
    """Stands in for latest_release: counts the questions, answers what it was told to."""

    def __init__(self, answer):
        self.answer, self.asked = answer, 0

    def __call__(self):
        self.asked += 1
        return self.answer


def at(moment):
    return lambda: moment


def test_the_cache_lives_under_xdg_cache_home_or_dot_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "x"))
    assert cache_dir() == tmp_path / "x" / "esbi-cli"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache_dir() == tmp_path / ".cache" / "esbi-cli"


def test_the_first_call_asks_and_remembers_and_a_day_later_it_asks_again(tmp_path):
    ask = Asker(V2)

    assert cached_latest(directory=tmp_path, now=at(T0), check=ask) == V2
    assert cached_latest(directory=tmp_path, now=at(T0 + timedelta(hours=23)), check=ask) == V2
    assert ask.asked == 1
    later = T0 + timedelta(seconds=CHECK_INTERVAL_SECONDS)
    cached_latest(directory=tmp_path, now=at(later), check=ask)
    assert ask.asked == 2
    saved = json.loads((tmp_path / "update.json").read_text())
    assert saved == {"checked_at": later.isoformat(), "latest": "0.2.0", "url": V2.url}


def test_force_asks_even_when_the_cache_is_fresh(tmp_path):
    ask = Asker(V2)
    cached_latest(directory=tmp_path, now=at(T0), check=ask)

    cached_latest(directory=tmp_path, now=at(T0), check=ask, force=True)

    assert ask.asked == 2


def test_a_failed_check_is_not_repeated_for_an_hour_and_keeps_what_was_known(tmp_path):
    cached_latest(directory=tmp_path, now=at(T0), check=Asker(V2))
    down = Asker(None)
    day = T0 + timedelta(days=1, minutes=1)

    assert cached_latest(directory=tmp_path, now=at(day), check=down) == V2  # stale beats nothing
    cached_latest(directory=tmp_path, now=at(day + timedelta(minutes=59)), check=down)
    assert down.asked == 1
    cached_latest(directory=tmp_path, now=at(day + timedelta(hours=1)), check=down)
    assert down.asked == 2


def test_an_offline_first_run_is_not_retried_on_every_command(tmp_path):
    down = Asker(None)

    assert cached_latest(directory=tmp_path, now=at(T0), check=down) is None
    assert cached_latest(directory=tmp_path, now=at(T0 + timedelta(minutes=5)), check=down) is None

    assert down.asked == 1


def test_force_reports_a_failed_check_as_none_instead_of_stale_news(tmp_path):
    cached_latest(directory=tmp_path, now=at(T0), check=Asker(V2))

    assert cached_latest(directory=tmp_path, now=at(T0), check=Asker(None), force=True) is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"checked_at": "yesterday", "latest": "0.2.0"}',
        '{"checked_at": 5, "latest": "0.2.0; rm -rf ~", "url": "javascript:x"}',
        '{"checked_at": "2999-01-01T00:00:00+00:00", "latest": "0.2.0"}',  # from the future
    ],
)
def test_a_damaged_or_hostile_cache_file_is_ignored_and_replaced(tmp_path, content):
    (tmp_path / "update.json").write_text(content)
    ask = Asker(V2)

    assert cached_latest(directory=tmp_path, now=at(T0), check=ask) == V2

    assert ask.asked == 1
    assert json.loads((tmp_path / "update.json").read_text())["latest"] == "0.2.0"


def test_a_cache_that_cannot_be_written_does_not_break_the_check(tmp_path):
    blocked = tmp_path / "file-not-a-folder"
    blocked.write_text("x")

    assert cached_latest(directory=blocked / "sub", now=at(T0), check=Asker(V2)) == V2
