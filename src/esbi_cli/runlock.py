"""Single-run guard: an OS-level file lock that dies with the process, so it can never get stuck."""

import fcntl
from pathlib import Path


class LockBusy(RuntimeError):
    pass


class RunLock:
    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            file.close()
            raise LockBusy(f"another run holds {self.path}") from None
        self._file = file
        return self

    def __exit__(self, *exc_info) -> None:
        if self._file:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None
