"""Settings loading: the SSH_JUMP_ADDRESS shape is validated at load time."""

import os

from twinlab_backend.config import load_settings
from twinlab_backend.result import Err, Ok


def _env(**extra: str) -> dict[str, str]:
    return {**os.environ, **extra}


def test_jump_address_host_port_accepted() -> None:
    loaded = load_settings(_env(SSH_JUMP_ADDRESS="labs.example.com:2222"))
    assert isinstance(loaded, Ok)
    assert loaded.value.ssh_jump_address == "labs.example.com:2222"


def test_jump_address_unset_means_not_advertised() -> None:
    env = {k: v for k, v in os.environ.items() if k != "SSH_JUMP_ADDRESS"}
    loaded = load_settings(env)
    assert isinstance(loaded, Ok)
    assert loaded.value.ssh_jump_address == ""
    assert loaded.value.ssh_jump_token is None


def test_jump_address_without_port_is_rejected() -> None:
    # A malformed advertisement must fail startup, not surface as a broken
    # ssh command in every client.
    for bad in ("labs.example.com", ":2222", "labs.example.com:0", "labs.example.com:port"):
        loaded = load_settings(_env(SSH_JUMP_ADDRESS=bad))
        assert isinstance(loaded, Err), bad
