import sys

import keyring.errors
import pytest
from conftest import FakeKeyring

from esbi_cli.mail.credentials import CredentialError, get_password, save_password


def test_the_password_lives_in_the_keychain_and_gmail_style_spaces_are_dropped():
    keychain = FakeKeyring()

    save_password("me@x.test", "abcd efgh ijkl mnop", backend=keychain)

    assert keychain.store == {("esbi-cli-imap", "me@x.test"): "abcdefghijklmnop"}
    assert get_password("me@x.test", backend=keychain) == "abcdefghijklmnop"


def test_a_missing_password_says_how_to_store_it():
    with pytest.raises(CredentialError, match="sb email set-password"):
        get_password("me@x.test", backend=FakeKeyring())


def test_a_keychain_that_cannot_be_used_is_reported_as_a_credential_problem(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")  # the macOS words: Linux says "system keyring"

    class Locked:
        def get_password(self, service, user):
            raise keyring.errors.KeyringLocked("The keychain is locked")

        def set_password(self, service, user, password):
            raise keyring.errors.PasswordSetError("denied")

    for action in (
        lambda: get_password("me@x.test", backend=Locked()),
        lambda: save_password("me@x.test", "pw", backend=Locked()),
    ):
        with pytest.raises(CredentialError, match="Keychain"):
            action()


def test_a_keychain_waiting_for_a_permission_dialog_times_out_instead_of_freezing_the_run(
    monkeypatch,
):
    """macOS asks "allow this program to use the item?" and the call blocks until someone clicks:
    an unattended nightly run would hang there, holding the run lock."""
    import threading

    monkeypatch.setattr(sys, "platform", "darwin")
    release = threading.Event()

    class WaitingForAClick:
        def get_password(self, service, user):
            release.wait(30)

    try:
        with pytest.raises(CredentialError, match="Always Allow"):
            get_password("me@x.test", backend=WaitingForAClick(), timeout_seconds=0.2)
    finally:
        release.set()


def test_an_item_owned_by_another_program_says_how_to_delete_it_so_the_new_password_can_be_stored():
    """Seen for real: macOS error -25244 when the tool was reinstalled, because the old Keychain
    item belongs to the previous Python and cannot be replaced by the new one."""

    class Foreign:
        def set_password(self, service, user, password):
            raise keyring.errors.PasswordSetError(
                "Can't store password on keychain: (-25244, 'Unknown Error')"
            )

    with pytest.raises(CredentialError) as error:
        save_password("me@x.test", "abcd efgh", backend=Foreign())

    text = str(error.value)
    assert "security delete-generic-password -s esbi-cli-imap -a me@x.test" in text


def test_on_linux_the_credential_problem_names_the_system_keyring_not_the_keychain(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    class Locked:
        def get_password(self, service, user):
            raise keyring.errors.KeyringLocked("locked")

    with pytest.raises(CredentialError, match="system keyring") as error:
        get_password("me@x.test", backend=Locked())

    assert "Keychain" not in str(error.value)
