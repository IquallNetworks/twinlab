"""Client secrets at rest (delta 33).

A client secret is sent to the token endpoint, so it must be RETRIEVABLE —
unlike session tokens and API keys it cannot be hashed. It is encrypted with
Fernet (AES-128-CBC + HMAC-SHA256) under OIDC_SECRET_KEY, so a database dump
does not hand out working client credentials. `cryptography` raises on a
wrong key or a tampered token; this module is the boundary that turns that
into a value.
"""

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class Unreadable:
    """The stored token does not decrypt under the configured key — the key
    was changed or lost. The fix is re-entering the secret."""


def encrypt(key: str, secret: str) -> str:
    return Fernet(key.encode()).encrypt(secret.encode()).decode()


def decrypt(key: str, token: str) -> Result[str, Unreadable]:
    try:
        return Ok(Fernet(key.encode()).decrypt(token.encode()).decode())
    except InvalidToken:
        return Err(Unreadable())
