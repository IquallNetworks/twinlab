"""OpenSSH public-key parser: pinned round-trip + every rejection reason."""

import base64
import struct

from twinlab_backend.auth.ssh_pubkey import parse_public_key
from twinlab_backend.result import Err, Ok

# A real ed25519 key, pinned with the fingerprint `ssh-keygen -lf` prints for
# it — the parser must agree byte-for-byte (it is sshd's %f lookup token).
_PINNED_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICqV0SzGoIXhwxC20lGKnnEfZhMb21y8MexZAcvJSUA9"
_PINNED_FINGERPRINT = "SHA256:JxvUfntD9iHd47w3m678qFFGpuTRRnJrA+rchUtcWhY"


def _blob(algorithm: str) -> bytes:
    return struct.pack(">I", len(algorithm)) + algorithm.encode() + b"\x00" * 16


def test_parses_pinned_key_with_comment() -> None:
    result = parse_public_key(f"{_PINNED_KEY} pinned@test\n")
    assert isinstance(result, Ok)
    key = result.value
    assert key.algorithm == "ssh-ed25519"
    assert key.fingerprint == _PINNED_FINGERPRINT
    assert key.comment == "pinned@test"
    assert key.key_b64 == _PINNED_KEY.split()[1]


def test_comment_is_optional() -> None:
    result = parse_public_key(_PINNED_KEY)
    assert isinstance(result, Ok)
    assert result.value.comment is None


def test_missing_key_material_is_invalid() -> None:
    result = parse_public_key("ssh-ed25519")
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_public_key"


def test_multiline_input_is_invalid() -> None:
    result = parse_public_key(f"{_PINNED_KEY}\n{_PINNED_KEY}")
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_public_key"


def test_bad_base64_is_invalid() -> None:
    result = parse_public_key("ssh-ed25519 !!!not-base64!!! comment")
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_public_key"


def test_truncated_blob_is_invalid() -> None:
    result = parse_public_key(f"ssh-ed25519 {base64.b64encode(b'ab').decode()}")
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_public_key"


def test_blob_algorithm_mismatch_is_invalid() -> None:
    # Valid base64, well-formed blob — but it names a different algorithm
    # than the outer field claims.
    line = f"ssh-ed25519 {base64.b64encode(_blob('ssh-rsa')).decode()}"
    result = parse_public_key(line)
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_public_key"


def test_unsupported_algorithm_is_distinct() -> None:
    # Structurally fine, just an obsolete type: a POLICY rejection, so the
    # client can say "unsupported" rather than "malformed".
    line = f"ssh-dss {base64.b64encode(_blob('ssh-dss')).decode()} old@host"
    result = parse_public_key(line)
    assert isinstance(result, Err)
    assert result.error.reason == "unsupported_key_type"
    assert result.error.detail == "ssh-dss"
