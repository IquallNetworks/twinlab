"""ssh-keygen subprocess boundary: real round-trip + failure mapping."""

import subprocess

import pytest

from twinlab_backend.auth import ssh_keygen
from twinlab_backend.auth.ssh_pubkey import parse_public_key
from twinlab_backend.result import Err, Ok


def test_generated_pair_round_trips_through_the_parser() -> None:
    generated = ssh_keygen.generate_ed25519("alice@twinlab")
    assert isinstance(generated, Ok)
    pair = generated.value
    assert pair.private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")

    parsed = parse_public_key(pair.public_key)
    assert isinstance(parsed, Ok)
    assert parsed.value.algorithm == "ssh-ed25519"
    assert parsed.value.comment == "alice@twinlab"


def test_each_call_yields_a_distinct_key() -> None:
    first = ssh_keygen.generate_ed25519("c")
    second = ssh_keygen.generate_ed25519("c")
    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert first.value.public_key != second.value.public_key


def test_subprocess_failure_is_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("ssh-keygen not found")

    monkeypatch.setattr(ssh_keygen.subprocess, "run", boom)
    generated = ssh_keygen.generate_ed25519("c")
    assert isinstance(generated, Err)
    assert "not found" in generated.error.detail
