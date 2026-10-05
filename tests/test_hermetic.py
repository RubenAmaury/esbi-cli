import os
import sys


def test_every_test_runs_as_on_a_mac_with_no_forced_colour():
    """macOS is the supported platform and CI runs on Linux: a test that wants another system says
    so with `monkeypatch.setattr(sys, "platform", ...)`. CI sets FORCE_COLOR, which styles help text."""
    assert sys.platform == "darwin"
    assert "FORCE_COLOR" not in os.environ
