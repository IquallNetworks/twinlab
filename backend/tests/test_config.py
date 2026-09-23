"""Settings loading: the SSH_JUMP_ADDRESS shape is validated at load time."""

import base64
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


def _without(*names: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in names}


def test_base_path_must_be_present_but_may_be_empty() -> None:
    # Delta 33: '' is the explicit "served at the origin root", so present-
    # and-empty loads while absent fails — a guessed base path would send a
    # browser to the wrong place after sign-in.
    root = load_settings(_env(FRONTEND_BASE_PATH=""))
    assert isinstance(root, Ok)
    assert root.value.frontend_base_path == ""

    absent = load_settings(_without("FRONTEND_BASE_PATH"))
    assert isinstance(absent, Err)
    assert "FRONTEND_BASE_PATH" in absent.error.message


def test_base_path_follows_the_frontend_build_rule() -> None:
    assert isinstance(load_settings(_env(FRONTEND_BASE_PATH="/twinlab")), Ok)
    for bad in ("twinlab", "/twinlab/", "/", "//x"):
        assert isinstance(load_settings(_env(FRONTEND_BASE_PATH=bad)), Err), bad


def test_bootstrap_admin_email_is_required_and_structural() -> None:
    assert isinstance(load_settings(_without("BOOTSTRAP_ADMIN_EMAIL")), Err)
    for bad in ("admin", "@example.com", "admin@", "ad min@example.com", "a@b@c"):
        assert isinstance(load_settings(_env(BOOTSTRAP_ADMIN_EMAIL=bad)), Err), bad


def test_public_origin_is_an_origin_or_unset() -> None:
    unset = load_settings(_without("PUBLIC_ORIGIN"))
    assert isinstance(unset, Ok)
    assert unset.value.public_origin == ""  # OIDC sign-in off

    for good in ("https://tools.example.com", "http://localhost:5173"):
        assert isinstance(load_settings(_env(PUBLIC_ORIGIN=good)), Ok), good
    for bad in ("tools.example.com", "https://tools.example.com/twinlab", "ftp://x", "https://"):
        assert isinstance(load_settings(_env(PUBLIC_ORIGIN=bad)), Err), bad


def test_oidc_secret_key_must_be_a_fernet_key() -> None:
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    loaded = load_settings(_env(OIDC_SECRET_KEY=key))
    assert isinstance(loaded, Ok)
    assert loaded.value.oidc_secret_key is not None

    short = base64.urlsafe_b64encode(b"k" * 16).decode()
    for bad in (short, "not base64 at all!"):
        assert isinstance(load_settings(_env(OIDC_SECRET_KEY=bad)), Err), bad

    unset = load_settings(_without("OIDC_SECRET_KEY"))
    assert isinstance(unset, Ok)
    assert unset.value.oidc_secret_key is None
