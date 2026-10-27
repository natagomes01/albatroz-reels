"""Secrets come from the OS secret store only (spec 4.6, 6.7): the macOS Keychain through
`security`, elsewhere the `keyring` package (Windows Credential Manager)."""
from __future__ import annotations

import getpass
import subprocess

from shorts import machine


class MissingSecret(RuntimeError):
    pass


def add_hint(service: str) -> str:
    return machine.install_hint("secret", service=service, user=getpass.getuser())


def has_secret(service: str, runner=subprocess.run) -> bool:
    """True when the store holds `service`; never reads the value on the Mac (no -w)."""
    if machine.secret_store() == "keyring":
        try:
            _get_keyring(service)
        except (MissingSecret, ImportError):
            return False
        return True
    try:
        return runner(["security", "find-generic-password", "-s", service],
                      capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def get_secret(service: str) -> str:
    if machine.secret_store() == "keyring":
        return _get_keyring(service)
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise MissingSecret(
            f"no Keychain item '{service}'. Add it with: {add_hint(service)}")
    return r.stdout.strip()


def _get_keyring(service: str) -> str:
    import keyring

    user = getpass.getuser()
    value = keyring.get_password(service, user)
    if not value or not value.strip():
        raise MissingSecret(
            f"no credential '{service}' for user '{user}'. Add it with: {add_hint(service)}")
    return value.strip()
