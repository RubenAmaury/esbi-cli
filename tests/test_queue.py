import sqlite3
from datetime import date

from esbi_cli.queue import Queue


def test_adding_the_same_url_twice_keeps_one_item_even_with_tracking_params(queue):
    assert queue.add("https://Example.com/post/?utm_source=share&id=7#top", origin="legacy") is True
    assert queue.add("https://example.com/post?id=7&utm_medium=x", origin="inbox") is False
    assert queue.add("https://example.com/post?id=8", origin="inbox") is True
    assert queue.counts() == {"queued": 2}


def test_claim_returns_oldest_first_and_completed_items_are_not_claimed_again(queue):
    for n in range(3):
        queue.add(f"https://x.test/{n}", origin="inbox")

    first = queue.claim(2)
    assert [i.target for i in first] == ["https://x.test/0", "https://x.test/1"]
    assert queue.counts() == {"processing": 2, "queued": 1}

    queue.complete(first[0].id)
    assert queue.claim(5)[0].target == "https://x.test/2"
    assert queue.counts() == {"done": 1, "processing": 3 - 1}


def test_failed_items_are_requeued_until_three_attempts_then_parked_with_their_error(queue):
    queue.add("https://x.test/a", origin="inbox")
    for attempt in (1, 2):
        item = queue.claim(1)[0]
        queue.fail(item.id, f"boom {attempt}")
        assert queue.counts() == {"queued": 1}

    queue.fail(queue.claim(1)[0].id, "boom 3")

    assert queue.counts() == {"failed": 1}
    assert queue.claim(1) == []
    [parked] = queue.items("failed")
    assert parked.error == "boom 3" and parked.attempts == 3


def test_items_left_processing_by_a_crashed_run_are_recovered_after_restart(tmp_path):
    path = tmp_path / "queue.sqlite3"
    first_run = Queue(path)
    first_run.add("https://x.test/a", origin="inbox")
    first_run.claim(1)  # the process dies here, before complete/fail

    second_run = Queue(path)
    assert second_run.recover() == 1
    assert second_run.counts() == {"queued": 1}


def park(queue, target):
    queue.add(target, origin="inbox")
    for _ in range(3):
        queue.fail(queue.claim(1)[0].id, "boom")


def test_retry_puts_parked_failures_back_all_or_just_one_with_a_fresh_attempt_count(queue):
    for n in range(3):
        park(queue, f"https://x.test/{n}")
    queue.add("https://x.test/fresh", origin="inbox")

    assert (
        queue.requeue_failed("https://x.test/1/?utm_medium=mail") == 1
    )  # same normalization as add
    assert queue.counts() == {"failed": 2, "queued": 2}
    [again] = [i for i in queue.items("queued") if i.target.endswith("/1")]
    assert (again.attempts, again.error) == (0, None)

    assert queue.requeue_failed() == 2
    assert queue.counts() == {"queued": 4}
    assert queue.requeue_failed("https://x.test/unknown") == 0


def test_drop_removes_an_item_in_any_state_and_lets_it_be_added_again(queue):
    park(queue, "https://x.test/bad")
    queue.add("https://x.test/waiting", origin="inbox")

    assert queue.remove("https://x.test/bad") is True
    assert queue.remove("https://x.test/waiting/#frag") is True
    assert queue.remove("https://x.test/never-there") is False
    assert queue.counts() == {}
    assert queue.add("https://x.test/bad", origin="inbox") is True


def test_items_remember_their_capture_date_and_display_label(queue):
    queue.add("https://x.test/a", origin="legacy", captured=date(2026, 8, 31))
    queue.add("/vault/raw/inbox/Post.md", origin="inbox", label="Mi post")

    a, post = queue.claim(2)

    assert (a.captured, a.label) == (date(2026, 8, 31), None)
    assert (post.captured, post.label) == (None, "Mi post")
    assert queue.get("https://x.test/a").captured == date(2026, 8, 31)
    assert queue.get("https://x.test/none") is None


def test_a_queue_database_created_before_these_columns_still_opens_and_keeps_its_items(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE items (id INTEGER PRIMARY KEY, target TEXT NOT NULL UNIQUE,
           origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
           attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
           added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    db.execute("INSERT INTO items (target, origin) VALUES ('https://x.test/old', 'legacy')")
    db.commit()
    db.close()

    queue = Queue(path)

    [old] = queue.claim(5)
    assert (old.target, old.captured, old.label) == ("https://x.test/old", None, None)
    assert queue.add("https://x.test/new", origin="inbox", captured=date(2026, 9, 1)) is True
