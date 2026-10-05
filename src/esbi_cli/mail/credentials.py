"""The IMAP app password lives in the macOS Keychain (via keyring), never in a file."""

import sys
import threading

import keyring
from keyring.errors import KeyringError, NoKeyringError

from esbi_cli.hostos import keychain

SERVICE = "esbi-cli-imap"
OLD_SERVICE = "secondbrain-imap"  # legacy: the name before esbi-cli


class CredentialError(RuntimeError):
    pass


NO_KEYRING = (
    "There is no keyring on this system to keep the password in (no Keychain, GNOME Keyring or "
    "KWallet running in your login session). Email capture needs one: it works on macOS and on a "
    "Linux desktop; a server, a container or WSL usually has none, and the nightly job (cron) "
    "cannot reach a desktop keyring either."
)


def save_password(user: str, password: str, backend=None) -> None:
    # Google shows app passwords in groups separated by spaces; the spaces are not part of it
    try:
        (backend or keyring).set_password(SERVICE, user, "".join(password.split()))
    except NoKeyringError as exc:
        raise CredentialError(NO_KEYRING) from exc
    except KeyringError as exc:
        hint = ""
        if "-25244" in str(exc):  # the existing item was made by another program (a reinstall)
            hint = (
                " The old item belongs to another program; delete it and try again: "
                f"security delete-generic-password -s {SERVICE} -a {user}"
            )
        raise CredentialError(f"Could not write to the {keychain()}: {exc}.{hint}") from exc


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
        if sys.platform == "darwin":
            wait = (
                "The Keychain is waiting for permission: a dialog on the Mac asks whether `sb` may "
                "use the item. Click Always Allow, or store the password again with "
                "`sb email set-password`."
            )
        else:
            wait = (
                "The system keyring did not answer: it may be locked or waiting for you to unlock "
                "it. Unlock it, or store the password again with `sb email set-password`."
            )
        raise CredentialError(wait)
    if isinstance(outcome.get("error"), NoKeyringError):
        raise CredentialError(NO_KEYRING) from outcome["error"]
    if isinstance(outcome.get("error"), KeyringError):  # locked or denied
        raise CredentialError(f"Could not read the {keychain()}: {outcome['error']}") from outcome[
            "error"
        ]
    if "error" in outcome:
        raise outcome["error"]
    password = outcome["password"]
    if not password:
        raise CredentialError(
            f"No IMAP password in the {keychain()} for {user}. Store it with `sb email set-password`."
        )
    return password
