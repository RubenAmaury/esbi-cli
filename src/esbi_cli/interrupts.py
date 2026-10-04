"""SIGINT and SIGTERM as an exception in the main thread, so the code that owns a resource can put
it back. Handlers exist only inside `handling()`. Within it a signal raises `Interrupted` only
inside `interruptible()` and outside `deferred()`; anywhere else it waits for the next safe point,
so a note is written whole or not at all.
"""

import signal
import sys
import threading
from contextlib import contextmanager

SIGNALS = (signal.SIGINT, signal.SIGTERM)

# ponytail: module state, one run per process; a per-run object if two runs ever share a process
_depth = 0  # a signal raises only at 0
_pending: int | None = None  # the first signal received; later ones are ignored while it is handled


class Interrupted(BaseException):
    """Not an Exception, like KeyboardInterrupt: `except Exception` must not turn it into a failure."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _handle(signum, frame) -> None:
    global _pending
    if _pending is None:
        _pending = signum
        if _depth == 0:
            raise Interrupted(signum)


def _raise_if_pending() -> None:
    if _depth == 0 and _pending is not None:
        raise Interrupted(_pending)


@contextmanager
def handling():
    """Install the handlers for the block, then restore the previous ones. The block is protected
    until `interruptible()`. Outside the main thread nothing is installed."""
    global _depth, _pending
    if threading.current_thread() is not threading.main_thread():  # signal.signal needs it
        yield
        return
    previous = {s: signal.signal(s, _handle) for s in SIGNALS}
    _depth, _pending = 1, None
    try:
        yield
    finally:
        _depth, _pending = 0, None
        for s, handler in previous.items():
            signal.signal(s, handler)


@contextmanager
def interruptible():
    """A signal raises `Interrupted` inside this block (one that came earlier raises on entry)."""
    global _depth
    _depth -= 1
    try:
        _raise_if_pending()
        yield
    finally:
        _depth += 1


@contextmanager
def deferred():
    """A signal inside this block waits until it ends. Costs nothing when no handler is installed."""
    global _depth
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
    _raise_if_pending()  # normal exit only: a real error is not replaced


@contextmanager
def exit_when_interrupted():
    """For commands with no queue (`sb ingest`, `sb reingest`): stop with the conventional code."""
    try:
        with handling(), interruptible():
            yield
    except Interrupted as exc:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from None
