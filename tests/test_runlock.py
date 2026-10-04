import pytest

from esbi_cli.runlock import LockBusy, RunLock


def test_only_one_run_holds_the_lock_and_it_is_free_again_after_release(tmp_path):
    path = tmp_path / ".esbi" / "run.lock"

    with RunLock(path):
        with pytest.raises(LockBusy):
            RunLock(path).__enter__()

    with RunLock(path):  # released on exit, even though the file is still there
        pass


def test_a_leftover_lock_file_from_a_crashed_run_does_not_block(tmp_path):
    path = tmp_path / "run.lock"
    path.write_text("pid 99999 died here")

    with RunLock(path):
        pass
