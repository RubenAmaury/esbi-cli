"""The IMAP app password lives in the macOS Keychain (via keyring), never in a file."""

import threading

import keyring
from keyring.errors import KeyringError

SERVICE = "esbi-cli-imap"
OLD_SERVICE = "secondbrain-imap"  # legacy: the name before esbi-cli


class CredentialError(RuntimeError):
    pass


def save_password(user: str, password: str, backend=None) -> None:
    # Google shows app passwords in groups separated by spaces; the spaces are not part of it
    try:
        (backend or keyring).set_password(SERVICE, user, "".join(password.split()))
    except KeyringError as exc:
        hint = ""
        if "-25244" in str(exc):  # the existing item was made by another program (a reinstall)
            hint = (
                " The old item belongs to another program; delete it and try again: "
                f"security delete-generic-password -s {SERVICE} -a {user}"
            )
        raise CredentialError(f"Could not write to the Keychain: {exc}.{hint}") from exc


def get_password(user: str, backend=None, timeout_seconds: float = 20) -> str:
    # macOS can show "allow this program to use the item?" and block until someone clicks; an
    # unattended run must not hang there holding the run lock, so the read has a time limit.
    # A daemon thread, so a read still blocked at exit cannot keep the process alive.
    outcome: dict = {}

    def read() -> None:
        try:
            store = backend or keyring
            outcome["password"] = store.get_password(SERVICE, user)
            if not outcome["password"] and (old := store.get_password(OLD_SERVICE, user)):
                store.set_password(SERVICE, user, old)  # move it to the new name
                outcome["password"] = old
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise CredentialError(
            "The Keychain is waiting for permission: a dialog on the Mac asks whether `sb` may use "
            "the item. Click Always Allow, or store the password again with `sb email set-password`."
        )
    if isinstance(outcome.get("error"), KeyringError):  # no backend (Linux/CI), locked or denied
        raise CredentialError(f"Could not read the Keychain: {outcome['error']}") from outcome[
            "error"
        ]
    if "error" in outcome:
        raise outcome["error"]
    password = outcome["password"]
    if not password:
        raise CredentialError(
            f"No IMAP password in the Keychain for {user}. Store it with `sb email set-password`."
        )
    return password
