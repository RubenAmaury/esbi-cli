"""Words for what the user sees: macOS-only things are named as such, never assumed."""

import sys


def this_machine() -> str:
    return "this Mac" if sys.platform == "darwin" else "this machine"


def keychain() -> str:
    """The password store of the system `keyring` talks to."""
    return "Keychain" if sys.platform == "darwin" else "system keyring"
