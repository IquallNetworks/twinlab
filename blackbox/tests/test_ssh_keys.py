"""SSH-key contract: registered public keys + the advertised jump coordinates.

Record surface only — the keys are exercised against the real jump host in
test_ssh_jump.py (deploy slice).
"""

import base64
import struct
from collections.abc import Callable
from pathlib import Path

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import DEFAULT_PASSWORD, SuiteConfig, UserClientFactory, create_bb_user
from _ssh import generate_keypair, keygen_fingerprint


def _wellformed_key_line(algorithm: str, comment: str = "bb-test") -> str:
    """A structurally valid authorized_keys line for an arbitrary algorithm:
    the blob's leading field names the algorithm, as real keys do."""
    blob = struct.pack(">I", len(algorithm)) + algorithm.encode() + b"\x00" * 16
    return f"{algorithm} {base64.b64encode(blob).decode()} {comment}"


async def test_ssh_key_lifecycle(make_user_client: UserClientFactory, tmp_path: Path) -> None:
    _, client = await make_user_client(None)
    private, public = generate_keypair(tmp_path)

    created = await client.create_ssh_key("laptop", public)
    assert created.name == "laptop"
    assert created.algorithm == "ssh-ed25519"
    # The standard OpenSSH fingerprint — byte-identical to `ssh-keygen -lf`.
    assert created.fingerprint == keygen_fingerprint(private)
    assert created.comment == "bb-suite"
    assert created.last_used_at is None

    assert await client.list_ssh_keys() == [created]

    await client.delete_ssh_key(created.id)
    assert await client.list_ssh_keys() == []
    with pytest.raises(TwinlabApiError) as excinfo:
        await client.delete_ssh_key(created.id)
    assert excinfo.value.status_code == 404


async def test_malformed_public_key_is_422(make_user_client: UserClientFactory) -> None:
    _, client = await make_user_client(None)
    bad_lines = [
        "not a key at all",
        "ssh-ed25519 !!!not-base64!!! comment",
        # Well-formed base64 whose blob names a DIFFERENT algorithm.
        "ssh-ed25519 " + _wellformed_key_line("ssh-rsa").split()[1],
    ]
    for line in bad_lines:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.create_ssh_key("bad", line)
        assert excinfo.value.status_code == 422, line
        assert excinfo.value.code == "invalid_public_key", line


async def test_unsupported_key_type_is_422(make_user_client: UserClientFactory) -> None:
    _, client = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.create_ssh_key("dss", _wellformed_key_line("ssh-dss"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "unsupported_key_type"


async def test_duplicate_name_is_409(make_user_client: UserClientFactory, tmp_path: Path) -> None:
    _, client = await make_user_client(None)
    _, public_a = generate_keypair(tmp_path, name="a")
    _, public_b = generate_keypair(tmp_path, name="b")
    _ = await client.create_ssh_key("laptop", public_a)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.create_ssh_key("laptop", public_b)
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "name_taken"


async def test_same_key_twice_is_409(make_user_client: UserClientFactory, tmp_path: Path) -> None:
    # Fingerprints are globally unique — even the same user can't register a
    # key twice under another name.
    _, client = await make_user_client(None)
    _, public = generate_keypair(tmp_path)
    _ = await client.create_ssh_key("laptop", public)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.create_ssh_key("desktop", public)
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "key_already_registered"


async def test_deleting_the_user_releases_their_keys(
    admin: TwinlabClient,
    config: SuiteConfig,
    make_user_client: UserClientFactory,
    unique: Callable[[str], str],
    tmp_path: Path,
) -> None:
    # Not via make_user_client for the first user: deleted mid-test, so the
    # factory's teardown would double-delete.
    summary = await create_bb_user(admin, unique("user"))
    _, public = generate_keypair(tmp_path)
    async with TwinlabClient(config.base_url) as first:
        _ = await first.login(summary.username, DEFAULT_PASSWORD)
        _ = await first.create_ssh_key("laptop", public)

    _, second = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await second.create_ssh_key("laptop", public)
    assert excinfo.value.status_code == 409

    # Deleting the holder cascades the key away — the only observable proof
    # without cross-user reads: the same key is registrable again.
    await admin.delete_user(summary.id)
    key = await second.create_ssh_key("laptop", public)
    assert key.fingerprint == keygen_fingerprint(tmp_path / "id_ed25519")


async def test_generated_key_lifecycle(make_user_client: UserClientFactory, tmp_path: Path) -> None:
    _, client = await make_user_client(None)

    generated = await client.generate_ssh_key("issued")
    assert generated.private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert generated.info.name == "issued"
    assert generated.info.algorithm == "ssh-ed25519"

    # The returned private key IS the registered key: ssh-keygen derives the
    # same fingerprint from it that the server registered.
    private = tmp_path / "issued_key"
    _ = private.write_text(generated.private_key)
    private.chmod(0o600)
    assert keygen_fingerprint(private) == generated.info.fingerprint

    # From here on it is an ordinary registered key.
    assert await client.list_ssh_keys() == [generated.info]
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.generate_ssh_key("issued")
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "name_taken"
    await client.delete_ssh_key(generated.info.id)
    assert await client.list_ssh_keys() == []


async def test_ssh_access_is_advertised(make_user_client: UserClientFactory) -> None:
    # The compose stack always configures the jump, so `enabled` is True here;
    # the disabled shape is covered by client unit tests.
    _, client = await make_user_client(None)
    access = await client.get_ssh_access()
    assert access.enabled
    assert access.host
    assert access.port
    assert access.user
