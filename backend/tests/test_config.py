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


def test_hostprep_pair_accepted_together_or_not_at_all() -> None:
    both = load_settings(_env(HOSTPREP_URL="http://host:8091", HOSTPREP_TOKEN="s3cret"))
    assert isinstance(both, Ok)
    assert both.value.hostprep_url == "http://host:8091"

    neither = {k: v for k, v in os.environ.items() if k not in ("HOSTPREP_URL", "HOSTPREP_TOKEN")}
    loaded = load_settings(neither)
    assert isinstance(loaded, Ok)
    assert loaded.value.hostprep_url == ""
    assert loaded.value.hostprep_token is None


def test_hostprep_half_configured_is_rejected() -> None:
    # URL and token are one feature; only one of them set is a configuration
    # mistake that must fail startup, not a deploy-time surprise.
    for extra in ({"HOSTPREP_URL": "http://host:8091"}, {"HOSTPREP_TOKEN": "s3cret"}):
        env = {k: v for k, v in os.environ.items() if k not in ("HOSTPREP_URL", "HOSTPREP_TOKEN")}
        loaded = load_settings({**env, **extra})
        assert isinstance(loaded, Err), extra
