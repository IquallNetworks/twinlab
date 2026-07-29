"""OpenSSH public-key parsing: validation + the standard SHA256 fingerprint.

Pure stdlib. A public key line is ``<algorithm> <base64-blob> [comment]``, and
the blob itself opens with ``uint32 length + algorithm`` — which must equal
the outer field (that redundancy is how OpenSSH detects corrupted lines).
"""

import base64
import binascii
import hashlib
import struct
from dataclasses import dataclass

from twinlab_backend.result import Err, Ok, Result

# Key types the jump accepts: everything a current OpenSSH generates. ssh-dss
# is obsolete (dropped by OpenSSH itself); anything not listed is a policy
# "unsupported", distinct from a malformed line.
SUPPORTED_ALGORITHMS = frozenset(
    {
        "ssh-ed25519",
        "ssh-rsa",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    }
)


@dataclass(frozen=True, slots=True)
class SshKeyParseError:
    reason: str  # "invalid_public_key" | "unsupported_key_type"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ParsedSshKey:
    algorithm: str
    key_b64: str  # canonical base64 of the blob (no options/comment)
    comment: str | None
    fingerprint: str  # "SHA256:<unpadded base64>" — sshd's %f token verbatim


def fingerprint(blob: bytes) -> str:
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode()


def parse_public_key(line: str) -> Result[ParsedSshKey, SshKeyParseError]:
    text = line.strip()
    if "\n" in text or "\r" in text:
        return Err(SshKeyParseError("invalid_public_key", "expected a single key line"))
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        return Err(
            SshKeyParseError("invalid_public_key", "expected '<algorithm> <base64> [comment]'")
        )
    algorithm, encoded = parts[0], parts[1]
    comment = parts[2].strip() if len(parts) == 3 else None
    try:
        blob = base64.b64decode(encoded, validate=True)
    except binascii.Error, ValueError:
        return Err(SshKeyParseError("invalid_public_key", "key material is not valid base64"))
    if len(blob) < 4:
        return Err(SshKeyParseError("invalid_public_key", "key blob is truncated"))
    (algorithm_length,) = struct.unpack(">I", blob[:4])
    inner = blob[4 : 4 + algorithm_length]
    if len(inner) != algorithm_length or inner != algorithm.encode():
        return Err(
            SshKeyParseError("invalid_public_key", "key blob does not match its declared algorithm")
        )
    if algorithm not in SUPPORTED_ALGORITHMS:
        return Err(SshKeyParseError("unsupported_key_type", algorithm))
    return Ok(
        ParsedSshKey(
            algorithm=algorithm,
            key_b64=base64.b64encode(blob).decode(),
            comment=comment,
            fingerprint=fingerprint(blob),
        )
    )
